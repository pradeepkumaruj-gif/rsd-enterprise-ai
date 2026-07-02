import { useState, useRef, useEffect } from "react"

const FONTS = [
  { label: "Default", value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  { label: "Serif", value: "Georgia, 'Times New Roman', serif" },
  { label: "Mono", value: "'Courier New', Courier, monospace" },
]

let chatIdCounter = 1

function App() {
  const [chats, setChats] = useState([{ id: 1, title: "New conversation", messages: [] }])
  const [activeChatId, setActiveChatId] = useState(1)
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 768)
  const [theme, setTheme] = useState("light")
  const [font, setFont] = useState(FONTS[0].value)
  const [streamingText, setStreamingText] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const recognitionRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const streamIntervalRef = useRef(null)

  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)

  const c = {
    bg: isDark ? "#1e1e1e" : "#ffffff",
    sidebar: isDark ? "#1a1a1a" : "#f7f7f7",
    border: isDark ? "#2e2e2e" : "#e8e8e8",
    text: isDark ? "#e8e8e8" : "#1a1a1a",
    text2: isDark ? "#777" : "#888",
    hover: isDark ? "#252525" : "#f0f0f0",
    active: isDark ? "#2a2a2a" : "#ebebeb",
    userBubble: isDark ? "#2d2d2d" : "#f0f0f0",
    inputBg: isDark ? "#2a2a2a" : "#f9f9f9",
  }

  const activeChat = chats.find(ch => ch.id === activeChatId)
  const messages = activeChat?.messages || []

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
    const bdr = isDark ? '#3a3a3a' : '#e5e5e5'
    const hBg = isDark ? '#252525' : '#fafafa'
    const txt = isDark ? '#e8e8e8' : '#1a1a1a'
    let html = `<div style="overflow-x:auto;margin:10px 0;border-radius:8px;border:1px solid ${bdr}"><table style="border-collapse:collapse;width:100%;font-size:14px">`
    rows.forEach((row, i) => {
      const cells = row.split('|').filter(c => c.trim())
      const isH = i === 0
      html += `<tr style="background:${isH ? hBg : 'transparent'}">`
      cells.forEach(cell => {
        // Clean asterisks inside table cells
        const cleanCell = cell.trim().replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\*(.*?)\*/g, '$1')
        const tag = isH ? 'th' : 'td'
        html += `<${tag} style="padding:10px 16px;border-bottom:1px solid ${bdr};color:${txt};text-align:left;${isH ? 'font-weight:600;font-size:13px' : 'font-size:14px'}">${cleanCell}</${tag}>`
      })
      html += '</tr>'
    })
    return html + '</table></div>'
  }

  const formatText = (text) => {
    if (!text) return ""
    
    // Remove --- lines
    text = text.replace(/^---+$/gm, '')
    
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
          // Bold — **text**
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          // Italic — *text*
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          // H3 — ### heading
          .replace(/^###\s+(.*)/g, `<div style="font-size:15px;font-weight:700;margin:14px 0 6px;text-align:left">$1</div>`)
          // H2 — ## heading
          .replace(/^##\s+(.*)/g, `<div style="font-size:16px;font-weight:700;margin:16px 0 6px;text-align:left">$1</div>`)
          // H1 — # heading
          .replace(/^#\s+(.*)/g, `<div style="font-size:18px;font-weight:700;margin:18px 0 8px;text-align:left">$1</div>`)
          // Bullet points
          .replace(/^[-•]\s+(.*)/g, `<div style="margin:2px 0;padding-left:16px;display:flex;gap:8px;align-items:flex-start;text-align:left"><span style="margin-top:7px;width:4px;height:4px;border-radius:50%;background:${isDark?'#888':'#555'};flex-shrink:0"></span><span>$1</span></div>`)
          // Code
          .replace(/`(.*?)`/g, `<code style="background:${isDark?'#2a2a2a':'#f0f0f0'};padding:2px 6px;border-radius:4px;font-size:13px;font-family:monospace">$1</code>`)
        
        result.push(formatted)
      }
    }
    if (tableLines.length > 0) result.push(renderTable(tableLines))
    
    return result
      .filter(l => l.trim() !== '')
      .join('\n')
      .replace(/\n/g, '<br/>')
      .replace(/<br\/><br\/>/g, '<br/>')
  }

  const sendMessage = async () => {
    if (!input.trim() || loading || isStreaming) return
    const msgText = input
    setInput("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"
    setLoading(true)

    setChats(prev => prev.map(ch => {
      if (ch.id !== activeChatId) return ch
      const isFirst = ch.messages.length === 0
      return {
        ...ch,
        title: isFirst ? msgText.slice(0, 30) + (msgText.length > 30 ? "..." : "") : ch.title,
        messages: [...ch.messages, { role: "user", content: msgText }]
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
      setLoading(false)
      streamResponse(data.reply, (fullText) => {
        setChats(prev => prev.map(ch =>
          ch.id !== activeChatId ? ch : {
            ...ch,
            messages: [...ch.messages, { role: "assistant", content: fullText }]
          }
        ))
      })
    } catch (error) {
      setLoading(false)
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : {
          ...ch,
          messages: [...ch.messages, { role: "assistant", content: "❌ Error! Dobara try karo." }]
        }
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

  const copyText = (text) => navigator.clipboard.writeText(text)

  // AI Message Component
  const AIMessage = ({ content }) => (
    <div style={{ display: "flex", gap: "16px", alignItems: "flex-start", marginBottom: "28px" }}>
      {/* No avatar — Claude style */}
      <div style={{ width: "32px", flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "15px", lineHeight: "1.75", color: c.text, textAlign: "left" }}
          dangerouslySetInnerHTML={{ __html: formatText(content) }} />
        <button onClick={() => copyText(content)} style={{
          background: "transparent", border: "none", cursor: "pointer",
          fontSize: "12px", color: c.text2, padding: "4px 0", marginTop: "6px",
          display: "flex", alignItems: "center", gap: "4px",
          opacity: 0.7,
        }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
          </svg>
          Copy
        </button>
      </div>
    </div>
  )

  return (
    <div style={{ display: "flex", height: "100vh", background: c.bg, color: c.text, fontFamily: font, overflow: "hidden" }}>

      {/* Mobile overlay */}
      {sidebarOpen && window.innerWidth < 768 && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 40 }} />
      )}

      {/* Sidebar */}
      {sidebarOpen && (
        <div style={{
          width: "240px", minWidth: "240px", background: c.sidebar,
          borderRight: `1px solid ${c.border}`, display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
          position: window.innerWidth < 768 ? "fixed" : "relative", zIndex: 50,
        }}>
          <div style={{ padding: "14px 12px 10px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px", padding: "2px 4px" }}>
              <span style={{ fontWeight: "700", fontSize: "16px" }}>RSD AI</span>
            </div>
            <button onClick={newChat} style={{
              width: "100%", padding: "8px 12px", background: "transparent",
              border: `1px solid ${c.border}`, borderRadius: "8px", color: c.text,
              cursor: "pointer", fontSize: "13px", display: "flex", alignItems: "center", gap: "8px",
              transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              New conversation
            </button>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px" }}>
            <p style={{ fontSize: "11px", color: c.text2, padding: "6px 8px 4px", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: "600" }}>Recents</p>
            {chats.map(ch => (
              <div key={ch.id}
                onClick={() => { setActiveChatId(ch.id); if (window.innerWidth < 768) setSidebarOpen(false) }}
                style={{
                  padding: "8px 10px", borderRadius: "6px", cursor: "pointer", marginBottom: "1px",
                  background: ch.id === activeChatId ? c.active : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = c.hover }}
                onMouseLeave={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = "transparent" }}
              >
                <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  {ch.title}
                </span>
                <button onClick={(e) => deleteChat(ch.id, e)} style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  color: c.text2, fontSize: "12px", padding: "1px 4px", opacity: 0,
                }}
                  onMouseEnter={e => e.target.style.opacity = 1}
                  onMouseLeave={e => e.target.style.opacity = 0}
                >✕</button>
              </div>
            ))}
          </div>

          <div style={{ padding: "10px 8px", borderTop: `1px solid ${c.border}` }}>
            <button onClick={() => setShowSettings(true)} style={{
              width: "100%", padding: "8px 12px", background: "transparent",
              border: "none", borderRadius: "6px", color: c.text2, cursor: "pointer",
              fontSize: "13px", display: "flex", alignItems: "center", gap: "8px",
              transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
              </svg>
              Settings
            </button>
          </div>
        </div>
      )}

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* Header */}
        <div style={{
          padding: "10px 16px", borderBottom: `1px solid ${c.border}`,
          display: "flex", alignItems: "center", gap: "12px",
          background: c.bg, flexShrink: 0,
        }}>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            padding: "5px", color: c.text2,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <span style={{ fontSize: "13px", color: c.text2, fontWeight: "500" }}>
            {activeChat?.title || "New conversation"}
          </span>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {messages.length === 0 && !isStreaming && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%", gap: "14px", padding: "40px 20px",
            }}>
              <p style={{ fontSize: "22px", fontWeight: "600" }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px", color: c.text2, textAlign: "center", maxWidth: "260px", lineHeight: "1.6" }}>
                Sales data ke baare mein kuch bhi poochho
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center", maxWidth: "380px", marginTop: "8px" }}>
                {["Top TSE kaun hai?", "Party wise month sale", "Total sales kitni?", "Brand performance"].map(q => (
                  <button key={q} onClick={() => setInput(q)} style={{
                    padding: "7px 14px", background: "transparent",
                    border: `1px solid ${c.border}`, borderRadius: "20px",
                    cursor: "pointer", fontSize: "13px", color: c.text,
                    transition: "all 0.15s",
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = c.hover}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >{q}</button>
                ))}
              </div>
            </div>
          )}

          {/* Message list — Claude style */}
          <div style={{ padding: "28px 24px 0" }}>
            {messages.map((m, i) => (
              <div key={i}>
                {m.role === "user" ? (
                  // User — right side bubble
                  <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "24px" }}>
                    <div style={{
                      maxWidth: "75%", background: c.userBubble,
                      padding: "10px 16px", borderRadius: "18px 18px 4px 18px",
                      fontSize: "15px", lineHeight: "1.6", color: c.text,
                      textAlign: "left",
                    }}>
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <AIMessage content={m.content} />
                )}
              </div>
            ))}

            {/* Streaming */}
            {isStreaming && (
              <div style={{ display: "flex", gap: "16px", alignItems: "flex-start", marginBottom: "28px" }}>
                <div style={{ width: "32px", flexShrink: 0 }} />
                <div style={{ flex: 1, fontSize: "15px", lineHeight: "1.75", color: c.text, textAlign: "left" }}
                  dangerouslySetInnerHTML={{ __html: formatText(streamingText) + `<span style="display:inline-block;width:2px;height:15px;background:${isDark?'#aaa':'#555'};margin-left:1px;animation:blink 1s infinite;vertical-align:text-bottom"></span>` }} />
              </div>
            )}

            {/* Loading dots */}
            {loading && (
              <div style={{ display: "flex", gap: "16px", alignItems: "center", marginBottom: "28px" }}>
                <div style={{ width: "32px", flexShrink: 0 }} />
                <div style={{ display: "flex", gap: "4px" }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{ width: "6px", height: "6px", borderRadius: "50%", background: isDark?"#666":"#bbb", animation: "bounce 1.2s infinite", animationDelay: `${i*0.15}s` }} />
                  ))}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        <div style={{ padding: "12px 24px 18px", background: c.bg, flexShrink: 0 }}>
          <div style={{ maxWidth: "680px", margin: "0 auto" }}>
            <div style={{
              background: c.inputBg, borderRadius: "12px",
              border: `1px solid ${c.border}`,
              display: "flex", alignItems: "flex-end", gap: "8px", padding: "10px 12px",
              boxShadow: isDark ? "none" : "0 1px 6px rgba(0,0,0,0.06)",
            }}>
              <textarea ref={textareaRef} value={input} onChange={handleInput} onKeyDown={handleKeyDown}
                placeholder="Write a message..." rows={1}
                style={{
                  flex: 1, background: "transparent", border: "none", outline: "none",
                  color: c.text, fontSize: "15px", resize: "none", lineHeight: "1.5",
                  maxHeight: "200px", overflowY: "auto", fontFamily: font,
                }}
              />
              <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                <button onClick={startVoice} style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  padding: "4px 6px", color: listening ? "#ef4444" : c.text2, fontSize: "15px",
                }}>{listening ? "🔴" : "🎤"}</button>
                <button onClick={sendMessage} disabled={!input.trim() || loading || isStreaming} style={{
                  background: input.trim() && !loading && !isStreaming ? (isDark?"#fff":"#1a1a1a") : (isDark?"#333":"#e0e0e0"),
                  border: "none", borderRadius: "8px", width: "32px", height: "32px",
                  cursor: input.trim() ? "pointer" : "default",
                  color: input.trim() && !loading && !isStreaming ? (isDark?"#000":"#fff") : c.text2,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  transition: "all 0.2s", flexShrink: 0,
                }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
                  </svg>
                </button>
              </div>
            </div>
            <p style={{ textAlign: "center", fontSize: "11px", color: c.text2, marginTop: "8px" }}>
              RSD AI can make mistakes. Please verify important data.
            </p>
          </div>
        </div>
      </div>

      {/* Settings */}
      {showSettings && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}
          onClick={() => setShowSettings(false)}>
          <div style={{ background: c.bg, borderRadius: "14px", width: "100%", maxWidth: "420px", border: `1px solid ${c.border}`, boxShadow: "0 20px 50px rgba(0,0,0,0.2)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${c.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "600", fontSize: "15px" }}>Settings</span>
              <button onClick={() => setShowSettings(false)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "18px", color: c.text2 }}>✕</button>
            </div>
            <div style={{ padding: "18px 20px" }}>
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "14px", textTransform: "uppercase", letterSpacing: "0.8px" }}>Appearance</p>
              <div style={{ marginBottom: "18px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", fontSize: "14px", marginBottom: "2px" }}>Theme</p>
                  <p style={{ fontSize: "12px", color: c.text2 }}>Interface color</p>
                </div>
                <div style={{ display: "flex", background: isDark?"#2a2a2a":"#f0f0f0", borderRadius: "8px", padding: "3px", gap: "2px" }}>
                  {[{ v: "light", icon: "☀️" }, { v: "system", icon: "💻" }, { v: "dark", icon: "🌙" }].map(t => (
                    <button key={t.v} onClick={() => setTheme(t.v)} style={{
                      padding: "5px 10px", border: "none", borderRadius: "6px", cursor: "pointer",
                      background: theme === t.v ? (isDark?"#444":"#fff") : "transparent",
                      fontSize: "14px", transition: "all 0.15s",
                    }}>{t.icon}</button>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", fontSize: "14px", marginBottom: "2px" }}>Font</p>
                  <p style={{ fontSize: "12px", color: c.text2 }}>Chat font style</p>
                </div>
                <select value={font} onChange={e => setFont(e.target.value)} style={{
                  background: isDark?"#2a2a2a":"#f0f0f0", border: `1px solid ${c.border}`, color: c.text,
                  padding: "6px 10px", borderRadius: "7px", fontSize: "13px", outline: "none",
                }}>
                  {FONTS.map(f => <option key={f.label} value={f.value}>{f.label}</option>)}
                </select>
              </div>
              <hr style={{ border: "none", borderTop: `1px solid ${c.border}`, margin: "16px 0" }} />
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>About</p>
              <div style={{ fontSize: "13px", color: c.text2, lineHeight: "2" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 Smart Sales Analytics</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; background: ${isDark?"#1e1e1e":"white"}; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-4px)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: ${isDark?"#333":"#ddd"}; border-radius: 2px; }
        textarea::placeholder { color: ${isDark?"#555":"#aaa"}; }
      `}</style>
    </div>
  )
}

export default App