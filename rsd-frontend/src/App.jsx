import { useState, useRef, useEffect } from "react"
import Chart from 'chart.js/auto'
import { Send, Plus, Menu, Sun, Moon, MessageSquare, Mic, MicOff, Copy, Check, Trash2, Settings, X, Download, FileSpreadsheet, FileText, FileDown } from "lucide-react"
import * as XLSX from "xlsx"
import ExcelJS from "exceljs"
import jsPDF from "jspdf"
import "jspdf-autotable"

const CHAT_HISTORY_KEY = "rsd_chat_history"
const MAX_SAVED_CHATS = 100

// Loads saved chats from localStorage (so refreshing the browser doesn't
// lose sidebar history). Falls back to a single fresh chat if nothing is
// saved yet, or if the saved data is corrupted/invalid for any reason.
function loadSavedChats() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY)
    if (!raw) return [{ id: 1, title: "New conversation", messages: [] }]
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length > 0) return parsed
  } catch (err) {
    console.error("Failed to load saved chats:", err)
  }
  return [{ id: 1, title: "New conversation", messages: [] }]
}

let chatIdCounter = 1

function TrendChart({ chartData, isDark }) {
  const canvasRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!canvasRef.current || !chartData) return
    if (chartRef.current) chartRef.current.destroy()

    const colors = ['#D97757', '#4A90D9', '#7ED957', '#F5A623', '#9B59B6', '#E74C3C', '#1ABC9C', '#F39C12']

    chartRef.current = new Chart(canvasRef.current, {
      type: chartData.type || 'line',
      data: {
        labels: chartData.labels,
        datasets: chartData.datasets.map((ds, i) => ({
          ...ds,
          borderColor: colors[i % colors.length],
          backgroundColor: colors[i % colors.length] + '33',
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: isDark ? '#ececec' : '#1a1a1a' } } },
        scales: {
          x: { ticks: { color: isDark ? '#ececec' : '#1a1a1a' } },
          y: { ticks: { color: isDark ? '#ececec' : '#1a1a1a' } },
        },
      },
    })

    return () => { if (chartRef.current) chartRef.current.destroy() }
  }, [chartData, isDark])

  if (!chartData) return null
  return (
    <div style={{ maxWidth: '600px', margin: '12px 0' }}>
      <canvas ref={canvasRef}></canvas>
    </div>
  )
}

export default function App() {
  const [chats, setChats] = useState(() => loadSavedChats())
  const [activeChatId, setActiveChatId] = useState(() => {
    const loaded = loadSavedChats()
    // Bump the counter past whatever IDs were already saved, so new chats
    // never accidentally reuse an old ID.
    const maxId = Math.max(...loaded.map(ch => ch.id))
    chatIdCounter = maxId
    return loaded[0].id
  })
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 768)
  const [theme, setTheme] = useState("light")
  const [streamingText, setStreamingText] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [copiedId, setCopiedId] = useState(null)
  const [downloadMenuId, setDownloadMenuId] = useState(null)
  const recognitionRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const streamIntervalRef = useRef(null)

  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  const accent = "#D97757"

  const c = {
    bg: isDark ? "#212121" : "#ffffff",
    sidebar: isDark ? "#181818" : "#f4f4f4",
    border: isDark ? "#2e2e2e" : "#e8e8e8",
    text: isDark ? "#ececec" : "#1a1a1a",
    text2: isDark ? "#777" : "#888",
    hover: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)",
    active: isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.07)",
    userBubble: isDark ? "#2f2f2f" : "#f0f0f0",
    inputBg: isDark ? "#2f2f2f" : "#f9f9f9",
  }

  const activeChat = chats.find(ch => ch.id === activeChatId)
  const messages = activeChat?.messages || []

  // Persist chat history to localStorage on every change -- capped at
  // MAX_SAVED_CHATS (keeping the most RECENT ones, dropping the oldest)
  // so the sidebar survives a page refresh without growing unbounded.
  useEffect(() => {
    try {
      const capped = chats.slice(0, MAX_SAVED_CHATS)
      localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(capped))
    } catch (err) {
      console.error("Failed to save chat history:", err)
    }
  }, [chats])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streamingText, loading])

  const newChat = () => {
    chatIdCounter++
    const newC = { id: chatIdCounter, title: "New conversation", messages: [] }
    setChats(prev => [newC, ...prev])
    setActiveChatId(chatIdCounter)
    setInput("")
    if (window.innerWidth < 768) setSidebarOpen(false)
  }

  const deleteChat = (id, e) => {
    e.stopPropagation()
    setChats(prev => {
      const remaining = prev.filter(c => c.id !== id)
      if (remaining.length === 0) {
        chatIdCounter++
        const fresh = { id: chatIdCounter, title: "New conversation", messages: [] }
        setActiveChatId(fresh.id)
        return [fresh]
      }
      if (activeChatId === id) setActiveChatId(remaining[0].id)
      return remaining
    })
  }

  const startVoice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { alert("Voice support nahi hai!"); return }
    const r = new SR()
    r.lang = "hi-IN"
    r.onresult = (e) => setInput(e.results[0][0].transcript)
    r.onend = () => setListening(false)
    r.start()
    recognitionRef.current = r
    setListening(true)
  }

  const copyText = (text, id) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const streamResponse = (fullText, onComplete) => {
    setIsStreaming(true)
    setStreamingText("")
    const words = fullText.split(" ")
    let idx = 0
    if (streamIntervalRef.current) clearInterval(streamIntervalRef.current)
    streamIntervalRef.current = setInterval(() => {
      if (idx < words.length) {
        setStreamingText(prev => prev + (idx === 0 ? "" : " ") + words[idx])
        idx++
      } else {
        clearInterval(streamIntervalRef.current)
        setIsStreaming(false)
        setStreamingText("")
        onComplete(fullText)
      }
    }, 15)
  }

  const renderTable = (lines) => {
    const rows = lines.filter(l => !l.match(/^\|[\s-|]+\|$/) && !l.includes('---'))
    if (!rows.length) return ''
    const bdr = isDark ? '#333333' : '#e8e8e8'
    const bdrHead = isDark ? '#555555' : '#333333'
    const txt = isDark ? '#ececec' : '#1a1a1a'

    const parsedRows = rows.map(row => row.split('|').filter(c => c.trim()).map(c => c.trim()))
    const headerCells = parsedRows[0]
    const bodyRows = parsedRows.slice(1)

    const isNumericCell = (v) => {
      const s = (v || '').replace(/\*\*/g, '').trim()
      return s === '' || s === '-' || /^[₹$]?-?[\d,]+\.?\d*%?$/.test(s)
    }
    const numericCols = headerCells.map((_, colIdx) =>
      bodyRows.length > 0 && bodyRows.every(r => isNumericCell(r[colIdx]))
    )

    let html = `<div style="overflow-x:auto;margin:14px 0"><table style="border-collapse:collapse;width:100%;font-size:14px">`
    html += '<thead><tr>'
    headerCells.forEach((cell, colIdx) => {
      const clean = cell.replace(/\*\*(.*?)\*\*/g, '$1')
      const align = numericCols[colIdx] ? 'right' : 'left'
      html += `<th style="padding:8px 12px;border-bottom:2px solid ${bdrHead};color:${txt};text-align:${align};font-weight:600;font-size:12.5px;white-space:normal;word-wrap:break-word;max-width:140px">${clean}</th>`
    })
    html += '</tr></thead><tbody>'
    bodyRows.forEach((cells, i) => {
      const isLast = i === bodyRows.length - 1
      html += '<tr>'
      cells.forEach((cell, colIdx) => {
        const clean = cell.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        const align = numericCols[colIdx] ? 'right' : 'left'
        html += `<td style="padding:12px 16px;border-bottom:${isLast ? 'none' : `1px solid ${bdr}`};color:${txt};text-align:${align};font-size:14px;vertical-align:top">${clean}</td>`
      })
      html += '</tr>'
    })
    return html + '</tbody></table></div>'
  }

  const stripMd = (s) => s.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1').trim()

  const hasTable = (text) => !!text && /\|[\s:]*-{2,}[\s:]*\|/.test(text)

  const parseMarkdownTables = (text) => {
    try {
      if (!text) return []
      const lines = text.replace(/\r\n/g, '\n').split('\n')
      const tables = []
      let block = []
      const flushBlock = () => {
        if (!block.length) return
        const dataLines = block.filter(l => !/^\|[\s:|-]+\|$/.test(l.trim()))
        if (dataLines.length >= 1) {
          const parsedRows = dataLines.map(l => {
            const trimmed = l.trim()
            const inner = trimmed.replace(/^\|/, '').replace(/\|$/, '')
            return inner.split('|').map(stripMd)
          })
          tables.push({ headers: parsedRows[0], rows: parsedRows.slice(1) })
        }
        block = []
      }
      for (const rawLine of lines) {
        const line = rawLine.trim()
        if (line.startsWith('|') && line.endsWith('|') && line.length > 1) {
          block.push(line)
        } else if (block.length) {
          flushBlock()
        }
      }
      flushBlock()
      return tables
    } catch (err) {
      console.error('parseMarkdownTables failed:', err)
      return []
    }
  }

  const exportToCSV = (tables, filename) => {
    const parts = tables.map(t => {
      const esc = (v) => `"${String(v).replace(/"/g, '""')}"`
      return [t.headers.map(esc).join(','), ...t.rows.map(r => r.map(esc).join(','))].join('\n')
    })
    const csv = parts.join('\n\n')
    const blob = new Blob(["\uFEFF" + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportToExcel = async (tables, filename) => {
    const wb = new ExcelJS.Workbook()
    tables.forEach((t, i) => {
      const ws = wb.addWorksheet(`Table ${i + 1}`)
      ws.addRow(t.headers)
      t.rows.forEach(r => ws.addRow(r))

      const headerRow = ws.getRow(1)
      headerRow.eachCell(cell => {
        cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11, name: 'Calibri' }
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F6FB2' } }
        cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true }
        cell.border = {
          top: { style: 'thin', color: { argb: 'FFAAAAAA' } },
          bottom: { style: 'thin', color: { argb: 'FFAAAAAA' } },
          left: { style: 'thin', color: { argb: 'FFAAAAAA' } },
          right: { style: 'thin', color: { argb: 'FFAAAAAA' } },
        }
      })
      headerRow.height = 32

      for (let r = 2; r <= ws.rowCount; r++) {
        const row = ws.getRow(r)
        row.eachCell(cell => {
          cell.font = { size: 10.5, name: 'Calibri' }
          cell.border = {
            top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
            bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
            left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
            right: { style: 'thin', color: { argb: 'FFE0E0E0' } },
          }
          cell.alignment = { vertical: 'top', wrapText: true }
        })
        if (r % 2 === 0) {
          row.eachCell(cell => {
            cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3F8FC' } }
          })
        }
      }

      t.headers.forEach((h, idx) => {
        let maxLen = String(h || '').length
        t.rows.forEach(row => {
          const val = String(row[idx] || '')
          if (val.length > maxLen) maxLen = val.length
        })
        ws.getColumn(idx + 1).width = Math.min(Math.max(maxLen + 2, 12), 42)
      })

      ws.views = [{ state: 'frozen', ySplit: 1 }]
    })

    const buffer = await wb.xlsx.writeBuffer()
    const blob = new Blob([buffer], { type: 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportToPDF = (tables, filename) => {
    const doc = new jsPDF()
    let y = 14
    doc.setFontSize(14)
    doc.text("RSD Enterprise AI - Report", 14, y)
    y += 8
    tables.forEach((t) => {
      doc.autoTable({ head: [t.headers], body: t.rows, startY: y, styles: { fontSize: 8 }, headStyles: { fillColor: [217, 119, 87] } })
      y = doc.lastAutoTable.finalY + 10
    })
    doc.save(`${filename}.pdf`)
  }

  const formatText = (text) => {
    if (!text) return ""
    text = text.replace(/^---+$/gm, '').replace(/^===+$/gm, '')
    const lines = text.split('\n')
    let result = []
    let tableLines = []
    let inTable = false
    for (let line of lines) {
      if (line.trim().startsWith('|') && line.includes('|')) {
        inTable = true
        tableLines.push(line)
      } else {
        if (inTable) {
          result.push(renderTable(tableLines))
          tableLines = []
          inTable = false
        }
        let f = line
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/^###\s+(.*)/g, `<div style="font-size:15px;font-weight:700;margin:12px 0 4px">$1</div>`)
          .replace(/^##\s+(.*)/g, `<div style="font-size:16px;font-weight:700;margin:14px 0 6px">$1</div>`)
          .replace(/^#\s+(.*)/g, `<div style="font-size:18px;font-weight:700;margin:16px 0 8px">$1</div>`)
          .replace(/^[-•]\s+(.*)/g, `<div style="margin:3px 0;padding-left:16px;display:flex;gap:8px;align-items:flex-start"><span style="margin-top:8px;width:4px;height:4px;border-radius:50%;background:#888;flex-shrink:0"></span><span>$1</span></div>`)
          .replace(/`(.*?)`/g, `<code style="background:${isDark ? '#333' : '#f0f0f0'};padding:2px 6px;border-radius:4px;font-size:13px;font-family:monospace">$1</code>`)
        result.push(f)
      }
    }
    if (tableLines.length > 0) result.push(renderTable(tableLines))
    return result.filter(l => l.trim() !== '').join('\n').replace(/\n/g, '<br/>')
  }

  const sendMessage = async () => {
    if (!input.trim() || loading || isStreaming) return
    const msgText = input
    const msgId = Date.now()
    setInput("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"
    setLoading(true)
    setChats(prev => prev.map(ch => {
      if (ch.id !== activeChatId) return ch
      const isFirst = ch.messages.length === 0
      return {
        ...ch,
        title: isFirst ? msgText.slice(0, 30) + (msgText.length > 30 ? "..." : "") : ch.title,
        messages: [...ch.messages, { id: msgId, role: "user", content: msgText }]
      }
    }))
    if (window.innerWidth < 768) setSidebarOpen(false)
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 60000)
      const response = await fetch("https://rsd-enterprise-ai-production.up.railway.app/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msgText,
          history: messages.slice(-6).map(m => ({ role: m.role, content: m.content }))
        }),
        signal: controller.signal
      })
      clearTimeout(timeout)
      const data = await response.json()
      setLoading(false)
      const aiId = Date.now()
      const downloadTable = data.download_table || null
      const chartData = data.chart_data || null
      streamResponse(data.reply, (fullText) => {
        setChats(prev => prev.map(ch =>
          ch.id !== activeChatId ? ch : { ...ch, messages: [...ch.messages, { id: aiId, role: "assistant", content: fullText, downloadTable, chartData }] }
        ))
      })
    } catch (error) {
      setLoading(false)
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : { ...ch, messages: [...ch.messages, { id: Date.now(), role: "assistant", content: "❌ Error! Dobara try karo." }] }
      ))
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const handleInput = (e) => {
    setInput(e.target.value)
    e.target.style.height = "auto"
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px"
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: c.bg, color: c.text, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", overflow: "hidden" }}>

      {sidebarOpen && window.innerWidth < 768 && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 40 }} />
      )}

      {sidebarOpen && (
        <div style={{
          width: "260px", minWidth: "260px", background: c.sidebar,
          display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
          position: window.innerWidth < 768 ? "fixed" : "relative", zIndex: 50,
        }}>
          <div style={{ padding: "12px" }}>
            <button onClick={newChat} style={{
              width: "100%", padding: "9px 12px", background: "transparent",
              border: `1px solid ${c.border}`, borderRadius: "8px", color: c.text,
              cursor: "pointer", fontSize: "13px", fontWeight: "500",
              display: "flex", alignItems: "center", gap: "8px", transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <Plus size={15} /> New chat
            </button>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
            <p style={{ fontSize: "11px", color: c.text2, padding: "6px 8px", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: "600" }}>Recents</p>
            {chats.map(ch => (
              <div key={ch.id}
                onClick={() => { setActiveChatId(ch.id); if (window.innerWidth < 768) setSidebarOpen(false) }}
                style={{
                  display: "flex", alignItems: "center", gap: "8px",
                  padding: "8px 10px", borderRadius: "6px", cursor: "pointer", marginBottom: "1px",
                  background: ch.id === activeChatId ? c.active : "transparent",
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = c.hover }}
                onMouseLeave={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = "transparent" }}
              >
                <MessageSquare size={13} color={c.text2} style={{ flexShrink: 0 }} />
                <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{ch.title}</span>
                <button onClick={(e) => deleteChat(ch.id, e)} style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  color: c.text2, padding: "2px", opacity: 0, flexShrink: 0,
                  display: "flex", alignItems: "center",
                }}
                  onMouseEnter={e => e.currentTarget.style.opacity = 1}
                  onMouseLeave={e => e.currentTarget.style.opacity = 0}
                ><Trash2 size={12} /></button>
              </div>
            ))}
          </div>

          <div style={{ padding: "10px 12px", borderTop: `1px solid ${c.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{
                width: "28px", height: "28px", borderRadius: "50%",
                background: accent, display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: "12px", fontWeight: "700", color: "white",
              }}>R</div>
              <span style={{ fontSize: "13px", fontWeight: "500" }}>RSD AI</span>
            </div>
            <div style={{ display: "flex", gap: "2px" }}>
              <button onClick={() => setShowSettings(true)} style={{
                background: "transparent", border: "none", cursor: "pointer",
                padding: "6px", borderRadius: "6px", color: c.text2, display: "flex",
              }}
                onMouseEnter={e => e.currentTarget.style.background = c.hover}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              ><Settings size={15} /></button>
              <button onClick={() => setTheme(t => t === "dark" ? "light" : "dark")} style={{
                background: "transparent", border: "none", cursor: "pointer",
                padding: "6px", borderRadius: "6px", color: c.text2, display: "flex",
              }}
                onMouseEnter={e => e.currentTarget.style.background = c.hover}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              >{isDark ? <Sun size={15} /> : <Moon size={15} />}</button>
            </div>
          </div>
        </div>
      )}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        <div style={{ padding: "10px 16px", borderBottom: `1px solid ${c.border}`, display: "flex", alignItems: "center", gap: "12px", background: c.bg, flexShrink: 0 }}>
          <button onClick={() => setSidebarOpen(s => !s)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            padding: "6px", borderRadius: "6px", color: c.text2, display: "flex",
          }}
            onMouseEnter={e => e.currentTarget.style.background = c.hover}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          ><Menu size={17} /></button>
          <span style={{ fontSize: "14px", fontWeight: "500", color: c.text2 }}>
            {activeChat?.title || "New conversation"}
          </span>
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>

          {messages.length === 0 && !isStreaming && (
            <div style={{ padding: "48px 24px 24px" }}>
              <p style={{ fontSize: "22px", fontWeight: "600", marginBottom: "8px" }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px", color: c.text2, marginBottom: "24px", lineHeight: "1.6" }}>
                Sales data ke baare mein kuch bhi poochho
              </p>
            </div>
          )}

          <div style={{ padding: "0 24px" }}>
            {messages.map((m, i) => (
              <div key={m.id || i} style={{ marginBottom: "8px" }}>
                {m.role === "user" ? (
                  <div style={{ display: "flex", justifyContent: "flex-end", padding: "16px 0 8px" }}>
                    <div style={{
                      maxWidth: "75%", background: c.userBubble, color: c.text,
                      padding: "10px 16px", borderRadius: "18px 18px 4px 18px",
                      fontSize: "15px", lineHeight: "1.6", textAlign: "left",
                    }}>{m.content}</div>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: "12px", alignItems: "flex-start", padding: "8px 0 4px" }}>
                    <div style={{
                      width: "28px", height: "28px", borderRadius: "50%",
                      background: accent, flexShrink: 0, marginTop: "2px",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "11px", fontWeight: "700", color: "white",
                    }}>R</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "15px", lineHeight: "1.75", color: c.text, textAlign: "left" }}
                        dangerouslySetInnerHTML={{ __html: formatText(m.content) }} />
                      {m.chartData && <TrendChart chartData={m.chartData} isDark={isDark} />}
                      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "6px", position: "relative" }}>
                        <button onClick={() => copyText(m.content, m.id)} style={{
                          background: "transparent", border: "none", cursor: "pointer",
                          color: c.text2, padding: "4px 0",
                          display: "flex", alignItems: "center", gap: "5px", fontSize: "12px", opacity: 0.7,
                        }}
                          onMouseEnter={e => e.currentTarget.style.opacity = 1}
                          onMouseLeave={e => e.currentTarget.style.opacity = 0.7}
                        >
                          {copiedId === m.id ? <><Check size={12} /> Copied!</> : <><Copy size={12} /> Copy</>}
                        </button>

                        {(m.downloadTable || hasTable(m.content)) && (
                          <>
                            <button onClick={() => setDownloadMenuId(downloadMenuId === m.id ? null : m.id)} style={{
                              background: "transparent", border: "none", cursor: "pointer",
                              color: c.text2, padding: "4px 0",
                              display: "flex", alignItems: "center", gap: "5px", fontSize: "12px", opacity: 0.7,
                            }}
                              onMouseEnter={e => e.currentTarget.style.opacity = 1}
                              onMouseLeave={e => e.currentTarget.style.opacity = 0.7}
                            >
                              <Download size={12} />
                              {m.downloadTable ? `Download (${m.downloadTable.rows.length} rows)` : "Download"}
                            </button>

                            {downloadMenuId === m.id && (
                              <>
                                <div onClick={() => setDownloadMenuId(null)} style={{ position: "fixed", inset: 0, zIndex: 60 }} />
                                <div style={{
                                  position: "absolute", top: "24px", left: "70px", zIndex: 70,
                                  background: c.bg, border: `1px solid ${c.border}`, borderRadius: "10px",
                                  boxShadow: "0 8px 24px rgba(0,0,0,0.15)", overflow: "hidden", minWidth: "150px",
                                }}>
                                  {[
                                    { label: "CSV", icon: <FileText size={13} />, fn: exportToCSV },
                                    { label: "Excel", icon: <FileSpreadsheet size={13} />, fn: exportToExcel },
                                    { label: "PDF", icon: <FileDown size={13} />, fn: exportToPDF },
                                  ].map(opt => (
                                    <button key={opt.label} onClick={() => {
                                      const tables = m.downloadTable
                                        ? [{ headers: m.downloadTable.headers, rows: m.downloadTable.rows }]
                                        : parseMarkdownTables(m.content)
                                      opt.fn(tables, `RSD-Report-${m.id}`)
                                      setDownloadMenuId(null)
                                    }} style={{
                                      width: "100%", padding: "9px 14px", background: "transparent", border: "none",
                                      cursor: "pointer", color: c.text, fontSize: "13px", textAlign: "left",
                                      display: "flex", alignItems: "center", gap: "8px",
                                    }}
                                      onMouseEnter={e => e.currentTarget.style.background = c.hover}
                                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                                    >{opt.icon} {opt.label}</button>
                                  ))}
                                </div>
                              </>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {isStreaming && (
              <div style={{ display: "flex", gap: "12px", alignItems: "flex-start", padding: "8px 0" }}>
                <div style={{
                  width: "28px", height: "28px", borderRadius: "50%",
                  background: accent, flexShrink: 0, marginTop: "2px",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "11px", fontWeight: "700", color: "white",
                }}>R</div>
                <div style={{ flex: 1, fontSize: "15px", lineHeight: "1.75", color: c.text, textAlign: "left" }}
                  dangerouslySetInnerHTML={{ __html: formatText(streamingText) + `<span style="display:inline-block;width:2px;height:15px;background:${accent};margin-left:1px;animation:blink 1s infinite;vertical-align:text-bottom"></span>` }} />
              </div>
            )}

            {loading && (
              <div style={{ display: "flex", gap: "12px", alignItems: "center", padding: "16px 0" }}>
                <div style={{
                  width: "28px", height: "28px", borderRadius: "50%",
                  background: accent, display: "flex", alignItems: "center",
                  justifyContent: "center", fontSize: "11px", fontWeight: "700", color: "white",
                }}>R</div>
                <div style={{ display: "flex", gap: "4px" }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{ width: "6px", height: "6px", borderRadius: "50%", background: isDark ? "#666" : "#bbb", animation: "bounce 1.2s infinite", animationDelay: `${i*0.15}s` }} />
                  ))}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <div style={{ padding: "12px 24px 20px", background: c.bg, flexShrink: 0 }}>
          <div style={{
            display: "flex", alignItems: "flex-end", gap: "8px",
            background: c.inputBg, borderRadius: "14px",
            border: `1px solid ${c.border}`, padding: "10px 12px",
            boxShadow: isDark ? "none" : "0 1px 8px rgba(0,0,0,0.06)",
          }}>
            <textarea ref={textareaRef} value={input} onChange={handleInput} onKeyDown={handleKeyDown}
              placeholder="Message RSD AI..." rows={1}
              style={{
                flex: 1, background: "transparent", border: "none", outline: "none",
                color: c.text, fontSize: "15px", resize: "none", lineHeight: "1.5",
                maxHeight: "200px", overflowY: "auto",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
              }}
            />
            <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
              <button onClick={startVoice} style={{
                background: listening ? accent : "transparent", border: "none",
                cursor: "pointer", padding: "7px", borderRadius: "8px",
                color: listening ? "white" : c.text2, display: "flex", transition: "all 0.2s",
              }}>{listening ? <MicOff size={16} /> : <Mic size={16} />}</button>
              <button onClick={sendMessage} disabled={!input.trim() || loading || isStreaming} style={{
                background: input.trim() && !loading && !isStreaming ? accent : (isDark ? "#333" : "#e0e0e0"),
                border: "none", cursor: input.trim() ? "pointer" : "default",
                padding: "7px", borderRadius: "8px", color: "white",
                display: "flex", alignItems: "center", flexShrink: 0, transition: "all 0.2s",
                opacity: !input.trim() || loading || isStreaming ? 0.5 : 1,
              }}><Send size={16} /></button>
            </div>
          </div>
        </div>
      </div>

      {showSettings && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}
          onClick={() => setShowSettings(false)}>
          <div style={{ background: c.bg, borderRadius: "14px", width: "100%", maxWidth: "400px", border: `1px solid ${c.border}`, boxShadow: "0 20px 50px rgba(0,0,0,0.2)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${c.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "600", fontSize: "15px" }}>Settings</span>
              <button onClick={() => setShowSettings(false)} style={{ background: "transparent", border: "none", cursor: "pointer", color: c.text2, display: "flex" }}><X size={18} /></button>
            </div>
            <div style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "3px" }}>Theme</p>
                  <p style={{ fontSize: "12px", color: c.text2 }}>Light ya Dark</p>
                </div>
                <div style={{ display: "flex", background: isDark ? "#2a2a2a" : "#f0f0f0", borderRadius: "8px", padding: "3px", gap: "2px" }}>
                  {[{ v: "light", icon: <Sun size={14} />, label: "Light" }, { v: "system", icon: "💻", label: "Auto" }, { v: "dark", icon: <Moon size={14} />, label: "Dark" }].map(t => (
                    <button key={t.v} onClick={() => setTheme(t.v)} style={{
                      padding: "5px 10px", border: "none", borderRadius: "6px", cursor: "pointer",
                      background: theme === t.v ? (isDark ? "#444" : "#fff") : "transparent",
                      color: c.text, fontSize: "13px", fontWeight: theme === t.v ? "600" : "400",
                      display: "flex", alignItems: "center", gap: "4px",
                      boxShadow: theme === t.v ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                    }}>{t.icon} {t.label}</button>
                  ))}
                </div>
              </div>
              <hr style={{ border: "none", borderTop: `1px solid ${c.border}`, margin: "16px 0" }} />
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>About</p>
              <div style={{ fontSize: "13px", color: c.text2, lineHeight: "2" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 Smart Sales Analytics</p>
                <p>⚡ FastAPI + Claude AI</p>
                <p>🚀 Deployed on Railway</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; background: ${isDark ? "#212121" : "white"}; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-4px)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: ${isDark ? "#333" : "#ddd"}; border-radius: 2px; }
        textarea::placeholder { color: ${isDark ? "#555" : "#aaa"}; }
      `}</style>
    </div>
  )
}