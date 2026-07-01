import { useState, useRef, useEffect, useCallback } from "react"

const FONTS = [
  { label: "Default", value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  { label: "Serif", value: "Georgia, 'Times New Roman', serif" },
  { label: "Mono", value: "'Courier New', Courier, monospace" },
  { label: "Roboto", value: "Roboto, Arial, sans-serif" },
]

let chatIdCounter = 1

// Toast Component
function Toast({ message, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3000)
    return () => clearTimeout(t)
  }, [onClose])
  return (
    <div style={{
      position: "fixed", bottom: "80px", left: "50%", transform: "translateX(-50%)",
      background: "#333", color: "white", padding: "10px 20px", borderRadius: "20px",
      fontSize: "13px", zIndex: 999, animation: "fadeIn 0.3s ease",
      boxShadow: "0 4px 12px rgba(0,0,0,0.2)"
    }}>
      {message}
    </div>
  )
}

// Streaming Text Component
function StreamingText({ text, isStreaming }) {
  const [displayed, setDisplayed] = useState("")
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    if (!isStreaming) { setDisplayed(text); return }
    setDisplayed("")
    setIdx(0)
  }, [text, isStreaming])

  useEffect(() => {
    if (!isStreaming || idx >= text.length) return
    const t = setTimeout(() => {
      setDisplayed(prev => prev + text[idx])
      setIdx(i => i + 1)
    }, 8)
    return () => clearTimeout(t)
  }, [idx, text, isStreaming])

  return displayed
}

function App() {
  const [chats, setChats] = useState([{ id: 1, title: "Naya Sawaal", messages: [] }])
  const [activeChatId, setActiveChatId] = useState(1)
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 768)
  const [theme, setTheme] = useState("light")
  const [font, setFont] = useState(FONTS[0].value)
  const [toast, setToast] = useState(null)
  const [streamingId, setStreamingId] = useState(null)
  const recognitionRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)

  const c = {
    bg: isDark ? "#212121" : "#ffffff",
    bg2: isDark ? "#2a2a2a" : "#f7f7f7",
    bg3: isDark ? "#2f2f2f" : "#f0f0f0",
    sidebar: isDark ? "#171717" : "#ffffff",
    border: isDark ? "#333" : "#e5e5e5",
    text: isDark ? "#ececec" : "#1a1a1a",
    text2: isDark ? "#aaa" : "#666",
    hover: isDark ? "#2a2a2a" : "#f5f5f5",
    active: isDark ? "#333" : "#efefef",
    userBubble: "#7c3aed",
    aiDot: "#e05d26",
    accent: "#e05d26",
  }

  const activeChat = chats.find(ch => ch.id === activeChatId)
  const messages = activeChat?.messages || []

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  const showToast = (msg) => setToast(msg)

  const copyText = (text) => {
    navigator.clipboard.writeText(text)
    showToast("✅ Copied!")
  }

  const newChat = () => {
    chatIdCounter++
    const newC = { id: chatIdCounter, title: "Naya Sawaal", messages: [] }
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
        const fresh = { id: chatIdCounter, title: "Naya Sawaal", messages: [] }
        setActiveChatId(fresh.id)
        return [fresh]
      }
      if (activeChatId === id) setActiveChatId(remaining[0].id)
      return remaining
    })
    showToast("🗑️ Chat deleted!")
  }

  const startVoice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { showToast("❌ Voice support nahi hai!"); return }
    const r = new SR()
    r.lang = "hi-IN"
    r.onresult = (e) => setInput(e.results[0][0].transcript)
    r.onend = () => setListening(false)
    r.start()
    recognitionRef.current = r
    setListening(true)
    showToast("🎤 Sun raha hoon...")
  }

  const renderTable = useCallback((tableLines) => {
    const rows = tableLines.filter(l => !l.match(/^\|[\s-|]+\|$/))
    if (rows.length === 0) return ''
    const borderColor = isDark ? '#444' : '#e0e0e0'
    const headerBg = isDark ? '#333' : '#f5f5f5'
    const textColor = isDark ? '#ececec' : '#1a1a1a'
    const altBg = isDark ? '#252525' : '#fafafa'

    let html = `<div style="overflow-x:auto;margin:12px 0;border-radius:8px;border:1px solid ${borderColor}"><table style="border-collapse:collapse;width:100%;font-size:14px">`
    rows.forEach((row, idx) => {
      const cells = row.split('|').filter(c => c.trim() !== '')
      const isHeader = idx === 0
      html += `<tr style="background:${isHeader ? headerBg : idx % 2 === 0 ? 'transparent' : altBg}">`
      cells.forEach(cell => {
        const tag = isHeader ? 'th' : 'td'
        html += `<${tag} style="padding:10px 14px;border-bottom:1px solid ${borderColor};${isHeader ? `font-weight:600;color:${textColor}` : `color:${textColor}`};text-align:left">${cell.trim()}</${tag}>`
      })
      html += '</tr>'
    })
    html += '</table></div>'
    return html
  }, [isDark])

  const formatText = useCallback((text) => {
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
        let formatted = line
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/^### (.*)/g, '<h4 style="margin:10px 0 4px;font-size:15px;font-weight:600">$1</h4>')
          .replace(/^## (.*)/g, '<h3 style="margin:12px 0 6px;font-size:16px;font-weight:700">$1</h3>')
          .replace(/^# (.*)/g, '<h2 style="margin:14px 0 8px;font-size:18px;font-weight:700">$1</h2>')
          .replace(/^- (.*)/g, `<div style="margin:3px 0;padding-left:20px;display:flex;gap:8px"><span style="color:${c.accent}">•</span><span>$1</span></div>`)
          .replace(/^\d+\. (.*)/g, `<div style="margin:3px 0;padding-left:20px">$1</div>`)
          .replace(/`(.*?)`/g, `<code style="background:${isDark ? '#333' : '#f0f0f0'};padding:2px 6px;border-radius:4px;font-family:monospace;font-size:13px">$1</code>`)
        result.push(formatted)
      }
    }
    if (tableLines.length > 0) result.push(renderTable(tableLines))
    return result.join('<br/>').replace(/<br\/><br\/>/g, '<br/>')
  }, [isDark, c.accent, renderTable])

  const sendMessage = async () => {
    if (!input.trim() || loading) return
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
        title: isFirst ? msgText.slice(0, 28) + (msgText.length > 28 ? "..." : "") : ch.title,
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
        body: JSON.stringify({ message: msgText }),
        signal: controller.signal
      })
      clearTimeout(timeout)
      const data = await response.json()
      const aiMsgId = Date.now()
      setStreamingId(aiMsgId)
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : {
          ...ch,
          messages: [...ch.messages, { id: aiMsgId, role: "assistant", content: data.reply }]
        }
      ))
      setTimeout(() => setStreamingId(null), data.reply.length * 8 + 500)
    } catch (error) {
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : {
          ...ch,
          messages: [...ch.messages, { id: Date.now(), role: "assistant", content: "❌ Error! Dobara try karo." }]
        }
      ))
      showToast("❌ Connection error!")
    } finally {
      setLoading(false)
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
    <div style={{ display: "flex", height: "100vh", background: c.bg, color: c.text, fontFamily: font, overflow: "hidden" }}>

      {/* Overlay for mobile */}
      {sidebarOpen && window.innerWidth < 768 && (
        <div onClick={() => setSidebarOpen(false)} style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 40
        }} />
      )}

      {/* Sidebar */}
      {sidebarOpen && (
        <div style={{
          width: "260px", minWidth: "260px",
          background: c.sidebar,
          borderRight: `1px solid ${c.border}`,
          display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
          position: window.innerWidth < 768 ? "fixed" : "relative",
          zIndex: 50,
          boxShadow: window.innerWidth < 768 ? "4px 0 20px rgba(0,0,0,0.15)" : "none",
          transition: "transform 0.3s ease",
        }}>
          <div style={{ padding: "16px 12px", borderBottom: `1px solid ${c.border}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px", padding: "0 4px" }}>
              <span style={{ fontSize: "20px" }}>🤖</span>
              <span style={{ fontWeight: "700", fontSize: "15px", color: c.text }}>RSD Enterprise AI</span>
            </div>
            <button onClick={newChat} style={{
              width: "100%", padding: "10px 14px",
              background: isDark ? "#2a2a2a" : "#f5f5f5",
              border: `1px solid ${c.border}`,
              borderRadius: "10px", color: c.text, cursor: "pointer",
              fontSize: "14px", fontWeight: "500",
              display: "flex", alignItems: "center", gap: "8px",
              transition: "all 0.2s",
            }}>
              ✏️ Naya Chat
            </button>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
            <p style={{ fontSize: "11px", color: c.text2, padding: "8px 8px 4px", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: "600" }}>
              Chat History
            </p>
            {chats.map(ch => (
              <div key={ch.id} onClick={() => { setActiveChatId(ch.id); if (window.innerWidth < 768) setSidebarOpen(false) }}
                style={{
                  padding: "10px 12px", borderRadius: "8px", cursor: "pointer", marginBottom: "2px",
                  background: ch.id === activeChatId ? c.active : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  transition: "background 0.15s",
                }}
                onMouseEnter={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = c.hover }}
                onMouseLeave={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = "transparent" }}
              >
                <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, color: c.text }}>
                  💬 {ch.title}
                </span>
                <button onClick={(e) => deleteChat(ch.id, e)} style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  color: c.text2, fontSize: "13px", padding: "2px 4px", flexShrink: 0,
                  opacity: 0.6, transition: "opacity 0.2s",
                }}
                  onMouseEnter={e => e.target.style.opacity = 1}
                  onMouseLeave={e => e.target.style.opacity = 0.6}
                >🗑️</button>
              </div>
            ))}
          </div>

          <div style={{ padding: "12px", borderTop: `1px solid ${c.border}` }}>
            <button onClick={() => setShowSettings(true)} style={{
              width: "100%", padding: "10px 14px", background: "transparent",
              border: "none", borderRadius: "8px", color: c.text2, cursor: "pointer",
              fontSize: "13px", display: "flex", alignItems: "center", gap: "8px",
              transition: "background 0.2s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              ⚙️ Settings
            </button>
          </div>
        </div>
      )}

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: c.bg, minWidth: 0 }}>

        {/* Header */}
        <div style={{
          padding: "12px 20px", borderBottom: `1px solid ${c.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: c.bg, flexShrink: 0,
          backdropFilter: "blur(10px)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{
              background: "transparent", border: "none", cursor: "pointer",
              fontSize: "18px", color: c.text2, padding: "6px", borderRadius: "6px",
              transition: "background 0.2s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >☰</button>
            <span style={{ fontWeight: "600", fontSize: "15px" }}>🤖 RSD Enterprise AI</span>
          </div>
          <button onClick={() => setShowSettings(true)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            fontSize: "18px", color: c.text2, padding: "6px", borderRadius: "6px",
            transition: "background 0.2s",
          }}
            onMouseEnter={e => e.currentTarget.style.background = c.hover}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >⚙️</button>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0" }}>
          {messages.length === 0 && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%", gap: "16px",
              padding: "40px 20px",
            }}>
              <div style={{
                width: "64px", height: "64px", borderRadius: "50%",
                background: `linear-gradient(135deg, ${c.accent}, #7c3aed)`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "28px", boxShadow: "0 8px 24px rgba(224,93,38,0.3)",
              }}>🤖</div>
              <p style={{ fontSize: "22px", fontWeight: "700", color: c.text }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px", color: c.text2, textAlign: "center", maxWidth: "300px", lineHeight: "1.6" }}>
                Sales data ke baare mein kuch bhi poochho — instant accurate report milegi!
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center", maxWidth: "400px" }}>
                {["Top TSE kaun hai?", "Party wise month sale", "Brand wise performance", "Total sales kitni?"].map(q => (
                  <button key={q} onClick={() => setInput(q)} style={{
                    padding: "8px 14px", background: c.bg3, border: `1px solid ${c.border}`,
                    borderRadius: "20px", cursor: "pointer", fontSize: "13px", color: c.text,
                    transition: "all 0.2s",
                  }}
                    onMouseEnter={e => { e.currentTarget.style.background = c.accent; e.currentTarget.style.color = "white"; e.currentTarget.style.borderColor = c.accent }}
                    onMouseLeave={e => { e.currentTarget.style.background = c.bg3; e.currentTarget.style.color = c.text; e.currentTarget.style.borderColor = c.border }}
                  >{q}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            m.role === "user" ? (
              <div key={m.id || i} style={{
                padding: "16px 20px",
                display: "flex", justifyContent: "flex-end",
                borderBottom: `1px solid ${c.border}`,
              }}>
                <div style={{ maxWidth: "70%" }}>
                  <div style={{
                    background: c.userBubble, color: "white",
                    padding: "12px 16px", borderRadius: "18px 18px 4px 18px",
                    fontSize: "15px", lineHeight: "1.6",
                    boxShadow: "0 2px 8px rgba(124,58,237,0.3)",
                  }}>
                    {m.content}
                  </div>
                </div>
              </div>
            ) : (
              <div key={m.id || i} style={{
                padding: "20px 0",
                background: c.bg2,
                borderBottom: `1px solid ${c.border}`,
              }}>
                <div style={{
                  maxWidth: "760px", margin: "0 auto", padding: "0 20px",
                  display: "flex", gap: "12px", alignItems: "flex-start",
                }}>
                  <div style={{
                    width: "32px", height: "32px", borderRadius: "50%",
                    background: `linear-gradient(135deg, ${c.accent}, #ff6b35)`,
                    flexShrink: 0, marginTop: "2px",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "14px", boxShadow: "0 2px 8px rgba(224,93,38,0.3)",
                  }}>🤖</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                      <p style={{ fontWeight: "600", fontSize: "13px", color: c.accent }}>RSD AI</p>
                      <button onClick={() => copyText(m.content)} style={{
                        background: "transparent", border: `1px solid ${c.border}`,
                        borderRadius: "6px", padding: "3px 8px", cursor: "pointer",
                        fontSize: "11px", color: c.text2, transition: "all 0.2s",
                      }}
                        onMouseEnter={e => { e.currentTarget.style.background = c.hover }}
                        onMouseLeave={e => { e.currentTarget.style.background = "transparent" }}
                      >📋 Copy</button>
                    </div>
                    <div style={{ lineHeight: "1.8", fontSize: "15px", color: c.text }}
                      dangerouslySetInnerHTML={{
                        __html: formatText(
                          m.id === streamingId
                            ? m.content.slice(0, Math.floor((Date.now() - m.id) / 8))
                            : m.content
                        )
                      }}
                    />
                  </div>
                </div>
              </div>
            )
          ))}

          {loading && (
            <div style={{ padding: "20px 0", background: c.bg2, borderBottom: `1px solid ${c.border}` }}>
              <div style={{ maxWidth: "760px", margin: "0 auto", padding: "0 20px", display: "flex", gap: "12px", alignItems: "center" }}>
                <div style={{
                  width: "32px", height: "32px", borderRadius: "50%",
                  background: `linear-gradient(135deg, ${c.accent}, #ff6b35)`,
                  flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px",
                }}>🤖</div>
                <div>
                  <p style={{ fontWeight: "600", fontSize: "13px", color: c.accent, marginBottom: "8px" }}>RSD AI</p>
                  <div style={{ display: "flex", gap: "5px", alignItems: "center" }}>
                    {[0,1,2].map(i => (
                      <div key={i} style={{
                        width: "8px", height: "8px", borderRadius: "50%",
                        background: c.accent, animation: "bounce 1.2s infinite",
                        animationDelay: `${i*0.2}s`, opacity: 0.7,
                      }} />
                    ))}
                    <span style={{ fontSize: "13px", color: c.text2, marginLeft: "4px" }}>Soch raha hoon...</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "16px 20px", background: c.bg, borderTop: `1px solid ${c.border}`, flexShrink: 0 }}>
          <div style={{
            maxWidth: "760px", margin: "0 auto",
            background: c.bg3, borderRadius: "16px",
            border: `1px solid ${c.border}`,
            display: "flex", alignItems: "flex-end", gap: "8px", padding: "10px 14px",
            boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
            transition: "border-color 0.2s, box-shadow 0.2s",
          }}>
            <textarea ref={textareaRef} value={input} onChange={handleInput} onKeyDown={handleKeyDown}
              placeholder="Sawaal likho ya mic dabao..." rows={1}
              style={{
                flex: 1, background: "transparent", border: "none", outline: "none",
                color: c.text, fontSize: "15px", resize: "none", lineHeight: "1.5",
                maxHeight: "200px", overflowY: "auto", fontFamily: font,
              }}
            />
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <button onClick={startVoice} style={{
                background: listening ? "#ff4444" : "transparent", border: "none",
                borderRadius: "8px", padding: "6px 8px", cursor: "pointer",
                fontSize: "18px", color: listening ? "white" : c.text2,
                transition: "all 0.2s",
              }}>{listening ? "🔴" : "🎤"}</button>
              <button onClick={sendMessage} disabled={!input.trim() || loading} style={{
                background: input.trim() && !loading ? `linear-gradient(135deg, ${c.accent}, #ff6b35)` : c.bg3,
                border: "none", borderRadius: "10px", padding: "8px 14px",
                cursor: input.trim() && !loading ? "pointer" : "default",
                color: input.trim() && !loading ? "white" : c.text2,
                fontSize: "16px", transition: "all 0.2s",
                boxShadow: input.trim() && !loading ? "0 2px 8px rgba(224,93,38,0.4)" : "none",
              }}>➤</button>
            </div>
          </div>
          <p style={{ textAlign: "center", fontSize: "11px", color: c.text2, marginTop: "8px" }}>
            Enter = Send • Shift+Enter = New line
          </p>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}
          onClick={() => setShowSettings(false)}>
          <div style={{
            background: c.bg, borderRadius: "20px", width: "100%", maxWidth: "480px",
            maxHeight: "80vh", overflowY: "auto", border: `1px solid ${c.border}`,
            boxShadow: "0 24px 60px rgba(0,0,0,0.3)",
            animation: "slideUp 0.3s ease",
          }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "20px 24px", borderBottom: `1px solid ${c.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "700", fontSize: "17px" }}>⚙️ Settings</span>
              <button onClick={() => setShowSettings(false)} style={{
                background: c.bg3, border: "none", cursor: "pointer",
                fontSize: "16px", color: c.text2, width: "28px", height: "28px",
                borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
              }}>✕</button>
            </div>
            <div style={{ padding: "24px" }}>
              <p style={{ fontWeight: "700", fontSize: "11px", color: c.text2, marginBottom: "16px", textTransform: "uppercase", letterSpacing: "1px" }}>Appearance</p>

              <div style={{ marginBottom: "24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "4px" }}>Theme</p>
                  <p style={{ fontSize: "13px", color: c.text2 }}>Color theme choose karo</p>
                </div>
                <div style={{ display: "flex", gap: "4px", background: c.bg3, borderRadius: "10px", padding: "3px" }}>
                  {[{ value: "light", icon: "☀️", label: "Light" }, { value: "system", icon: "💻", label: "Auto" }, { value: "dark", icon: "🌙", label: "Dark" }].map(t => (
                    <button key={t.value} onClick={() => setTheme(t.value)} style={{
                      padding: "6px 12px", border: "none", borderRadius: "8px", cursor: "pointer",
                      background: theme === t.value ? (isDark ? "#444" : "#fff") : "transparent",
                      color: c.text, fontSize: "13px", fontWeight: theme === t.value ? "600" : "400",
                      boxShadow: theme === t.value ? "0 1px 4px rgba(0,0,0,0.15)" : "none",
                      transition: "all 0.2s",
                    }}>{t.icon} {t.label}</button>
                  ))}
                </div>
              </div>

              <div style={{ marginBottom: "24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "4px" }}>Chat Font</p>
                  <p style={{ fontSize: "13px", color: c.text2 }}>Font style choose karo</p>
                </div>
                <select value={font} onChange={e => setFont(e.target.value)} style={{
                  background: c.bg3, border: `1px solid ${c.border}`, color: c.text,
                  padding: "8px 12px", borderRadius: "8px", fontSize: "14px", outline: "none", cursor: "pointer",
                }}>
                  {FONTS.map(f => <option key={f.label} value={f.value}>{f.label}</option>)}
                </select>
              </div>

              <hr style={{ border: "none", borderTop: `1px solid ${c.border}`, margin: "20px 0" }} />
              <p style={{ fontWeight: "700", fontSize: "11px", color: c.text2, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "1px" }}>About</p>
              <div style={{ fontSize: "14px", color: c.text2, lineHeight: "2" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 Smart Sales Analytics</p>
                <p>⚡ FastAPI + Claude AI</p>
                <p>🚀 Deployed on Railway</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; background: white; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }
        @keyframes fadeIn { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideUp { from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:translateY(0)} }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #ddd; border-radius: 3px; }
        textarea::placeholder { color: #aaa; }
      `}</style>
    </div>
  )
}

export default App