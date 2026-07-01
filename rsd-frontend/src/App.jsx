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
    bg2: isDark ? "#2a2a2a" : "#f9f9f9",
    bg3: isDark ? "#333" : "#f0f0f0",
    sidebar: isDark ? "#171717" : "#f7f7f7",
    border: isDark ? "#3a3a3a" : "#e8e8e8",
    text: isDark ? "#ececec" : "#1a1a1a",
    text2: isDark ? "#888" : "#666",
    hover: isDark ? "#2a2a2a" : "#efefef",
    active: isDark ? "#333" : "#e8e8e8",
    accent: "#d97706",
    userBubble: isDark ? "#2d2d2d" : "#f0f0f0",
    userText: isDark ? "#ececec" : "#1a1a1a",
  }

  const activeChat = chats.find(ch => ch.id === activeChatId)
  const messages = activeChat?.messages || []

  // Auto scroll — har message pe
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

  // Word by word streaming
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
    }, 30)
  }

  const formatText = (text) => {
    if (!text) return ""
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
          .replace(/^## (.*)/g, `<div style="font-size:16px;font-weight:700;margin:12px 0 6px;color:${c.text}">$1</div>`)
          .replace(/^# (.*)/g, `<div style="font-size:18px;font-weight:700;margin:14px 0 8px;color:${c.text}">$1</div>`)
          .replace(/^- (.*)/g, `<div style="margin:3px 0;padding-left:16px;display:flex;gap:8px"><span style="color:${c.accent}">•</span><span>$1</span></div>`)
          .replace(/`(.*?)`/g, `<code style="background:${isDark?'#333':'#f0f0f0'};padding:1px 5px;border-radius:4px;font-size:13px;font-family:monospace">$1</code>`)
        result.push(formatted)
      }
    }
    if (tableLines.length > 0) result.push(renderTable(tableLines))
    return result.join('<br/>').replace(/<br\/><br\/>/g, '<br/>')
  }

  const renderTable = (lines) => {
    const rows = lines.filter(l => !l.match(/^\|[\s-|]+\|$/))
    if (!rows.length) return ''
    const bdr = isDark ? '#444' : '#e0e0e0'
    const hBg = isDark ? '#2a2a2a' : '#f5f5f5'
    const txt = isDark ? '#ececec' : '#1a1a1a'
    let html = `<div style="overflow-x:auto;margin:12px 0;border-radius:8px;border:1px solid ${bdr}"><table style="border-collapse:collapse;width:100%;font-size:14px">`
    rows.forEach((row, i) => {
      const cells = row.split('|').filter(c => c.trim())
      const isH = i === 0
      html += `<tr style="background:${isH ? hBg : 'transparent'}">`
      cells.forEach(cell => {
        const tag = isH ? 'th' : 'td'
        html += `<${tag} style="padding:10px 14px;border-bottom:1px solid ${bdr};color:${txt};text-align:left;${isH ? 'font-weight:600' : ''}">${cell.trim()}</${tag}>`
      })
      html += '</tr>'
    })
    return html + '</table></div>'
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

  const copyText = (text) => {
    navigator.clipboard.writeText(text)
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: c.bg, color: c.text, fontFamily: font, overflow: "hidden" }}>

      {/* Mobile overlay */}
      {sidebarOpen && window.innerWidth < 768 && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 40 }} />
      )}

      {/* Sidebar — Claude style */}
      {sidebarOpen && (
        <div style={{
          width: "260px", minWidth: "260px", background: c.sidebar,
          borderRight: `1px solid ${c.border}`, display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
          position: window.innerWidth < 768 ? "fixed" : "relative", zIndex: 50,
          boxShadow: window.innerWidth < 768 ? "4px 0 20px rgba(0,0,0,0.15)" : "none",
        }}>
          {/* Logo */}
          <div style={{ padding: "16px", borderBottom: `1px solid ${c.border}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "14px", padding: "4px" }}>
              <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: c.accent, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "14px" }}>🤖</div>
              <span style={{ fontWeight: "700", fontSize: "14px" }}>RSD Enterprise AI</span>
            </div>
            <button onClick={newChat} style={{
              width: "100%", padding: "9px 14px", background: "transparent",
              border: `1px solid ${c.border}`, borderRadius: "8px", color: c.text,
              cursor: "pointer", fontSize: "14px", display: "flex", alignItems: "center", gap: "8px",
              transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <span style={{ fontSize: "16px" }}>✏️</span> New conversation
            </button>
          </div>

          {/* Chat list */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
            <p style={{ fontSize: "11px", color: c.text2, padding: "6px 8px", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: "600" }}>Recents</p>
            {chats.map(ch => (
              <div key={ch.id} onClick={() => { setActiveChatId(ch.id); if (window.innerWidth < 768) setSidebarOpen(false) }}
                style={{
                  padding: "9px 10px", borderRadius: "6px", cursor: "pointer", marginBottom: "1px",
                  background: ch.id === activeChatId ? c.active : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = c.hover }}
                onMouseLeave={e => { if (ch.id !== activeChatId) e.currentTarget.style.background = "transparent" }}
              >
                <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, color: c.text }}>
                  {ch.title}
                </span>
                <button onClick={(e) => deleteChat(ch.id, e)} style={{
                  background: "transparent", border: "none", cursor: "pointer",
                  color: c.text2, fontSize: "12px", padding: "2px 4px", opacity: 0,
                  transition: "opacity 0.2s",
                }}
                  onMouseEnter={e => e.target.style.opacity = 1}
                  onMouseLeave={e => e.target.style.opacity = 0}
                >🗑️</button>
              </div>
            ))}
          </div>

          {/* Settings */}
          <div style={{ padding: "12px", borderTop: `1px solid ${c.border}` }}>
            <button onClick={() => setShowSettings(true)} style={{
              width: "100%", padding: "9px 14px", background: "transparent",
              border: "none", borderRadius: "8px", color: c.text2, cursor: "pointer",
              fontSize: "13px", display: "flex", alignItems: "center", gap: "8px",
              transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >⚙️ Settings</button>
          </div>
        </div>
      )}

      {/* Main area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* Header */}
        <div style={{
          padding: "12px 16px", borderBottom: `1px solid ${c.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: c.bg, flexShrink: 0,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{
              background: "transparent", border: "none", cursor: "pointer",
              padding: "6px", borderRadius: "6px", color: c.text2, fontSize: "18px",
              transition: "background 0.15s",
            }}
              onMouseEnter={e => e.currentTarget.style.background = c.hover}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >☰</button>
            <span style={{ fontSize: "14px", fontWeight: "600", color: c.text }}>
              {activeChat?.title || "New conversation"}
            </span>
          </div>
          <button onClick={() => setShowSettings(true)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            padding: "6px", borderRadius: "6px", color: c.text2, fontSize: "16px",
          }}>⚙️</button>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 0" }}>
          {messages.length === 0 && !isStreaming && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%", gap: "16px", padding: "40px 20px",
            }}>
              <div style={{
                width: "56px", height: "56px", borderRadius: "50%",
                background: c.accent, display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: "24px",
              }}>🤖</div>
              <p style={{ fontSize: "20px", fontWeight: "700" }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px", color: c.text2, textAlign: "center", maxWidth: "280px", lineHeight: "1.6" }}>
                Sales data ke baare mein kuch bhi poochho
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center", maxWidth: "380px", marginTop: "8px" }}>
                {["Top TSE kaun hai?", "Party wise month sale", "Brand wise performance", "Total sales kitni?"].map(q => (
                  <button key={q} onClick={() => setInput(q)} style={{
                    padding: "8px 14px", background: "transparent",
                    border: `1px solid ${c.border}`, borderRadius: "20px",
                    cursor: "pointer", fontSize: "13px", color: c.text,
                    transition: "all 0.2s",
                  }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = c.accent; e.currentTarget.style.color = c.accent }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = c.border; e.currentTarget.style.color = c.text }}
                  >{q}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: "0" }}>
              {m.role === "user" ? (
                // User — right side
                <div style={{ display: "flex", justifyContent: "flex-end", padding: "8px 24px" }}>
                  <div style={{
                    maxWidth: "65%", background: c.userBubble, color: c.userText,
                    padding: "12px 16px", borderRadius: "18px 18px 4px 18px",
                    fontSize: "15px", lineHeight: "1.6",
                  }}>
                    {m.content}
                  </div>
                </div>
              ) : (
                // AI — left side, Claude style
                <div style={{ padding: "16px 24px", borderBottom: `1px solid ${c.border}` }}>
                  <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", gap: "12px" }}>
                    <div style={{
                      width: "28px", height: "28px", borderRadius: "50%",
                      background: c.accent, flexShrink: 0, marginTop: "2px",
                      display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px",
                    }}>🤖</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                        <span style={{ fontSize: "13px", fontWeight: "600", color: c.accent }}>RSD AI</span>
                        <button onClick={() => copyText(m.content)} style={{
                          background: "transparent", border: `1px solid ${c.border}`,
                          borderRadius: "5px", padding: "3px 8px", cursor: "pointer",
                          fontSize: "11px", color: c.text2,
                        }}>Copy</button>
                      </div>
                      <div style={{ fontSize: "15px", lineHeight: "1.8", color: c.text }}
                        dangerouslySetInnerHTML={{ __html: formatText(m.content) }} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Streaming text — word by word */}
          {isStreaming && (
            <div style={{ padding: "16px 24px", borderBottom: `1px solid ${c.border}` }}>
              <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", gap: "12px" }}>
                <div style={{
                  width: "28px", height: "28px", borderRadius: "50%",
                  background: c.accent, flexShrink: 0, marginTop: "2px",
                  display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px",
                }}>🤖</div>
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: "13px", fontWeight: "600", color: c.accent, display: "block", marginBottom: "8px" }}>RSD AI</span>
                  <div style={{ fontSize: "15px", lineHeight: "1.8", color: c.text }}
                    dangerouslySetInnerHTML={{ __html: formatText(streamingText) + '<span style="display:inline-block;width:2px;height:16px;background:' + c.accent + ';margin-left:2px;animation:blink 1s infinite;vertical-align:text-bottom"></span>' }} />
                </div>
              </div>
            </div>
          )}

          {/* Loading dots */}
          {loading && (
            <div style={{ padding: "16px 24px" }}>
              <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", gap: "12px", alignItems: "center" }}>
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: c.accent, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px" }}>🤖</div>
                <div style={{ display: "flex", gap: "4px", paddingTop: "4px" }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{ width: "7px", height: "7px", borderRadius: "50%", background: c.accent, animation: "bounce 1.2s infinite", animationDelay: `${i*0.15}s`, opacity: 0.7 }} />
                  ))}
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input — Claude style */}
        <div style={{ padding: "16px 24px 20px", background: c.bg, flexShrink: 0 }}>
          <div style={{
            maxWidth: "720px", margin: "0 auto",
            background: c.bg3, borderRadius: "12px",
            border: `1px solid ${c.border}`,
            display: "flex", alignItems: "flex-end", gap: "8px", padding: "12px 14px",
            boxShadow: isDark ? "none" : "0 1px 8px rgba(0,0,0,0.06)",
          }}>
            <textarea ref={textareaRef} value={input} onChange={handleInput} onKeyDown={handleKeyDown}
              placeholder="Message RSD AI..." rows={1}
              style={{
                flex: 1, background: "transparent", border: "none", outline: "none",
                color: c.text, fontSize: "15px", resize: "none", lineHeight: "1.5",
                maxHeight: "200px", overflowY: "auto", fontFamily: font,
              }}
            />
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <button onClick={startVoice} style={{
                background: listening ? "#ef4444" : "transparent", border: "none",
                borderRadius: "6px", padding: "5px 7px", cursor: "pointer",
                fontSize: "16px", color: listening ? "white" : c.text2,
              }}>{listening ? "🔴" : "🎤"}</button>
              <button onClick={sendMessage} disabled={!input.trim() || loading || isStreaming} style={{
                background: input.trim() && !loading && !isStreaming ? c.accent : (isDark ? "#444" : "#ddd"),
                border: "none", borderRadius: "8px", width: "34px", height: "34px",
                cursor: input.trim() ? "pointer" : "default",
                color: "white", fontSize: "16px", display: "flex", alignItems: "center", justifyContent: "center",
                transition: "background 0.2s",
              }}>↑</button>
            </div>
          </div>
          <p style={{ textAlign: "center", fontSize: "11px", color: c.text2, marginTop: "8px" }}>
            RSD Enterprise AI — Sales Analytics
          </p>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}
          onClick={() => setShowSettings(false)}>
          <div style={{ background: c.bg, borderRadius: "16px", width: "100%", maxWidth: "460px", maxHeight: "80vh", overflowY: "auto", border: `1px solid ${c.border}`, boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "18px 22px", borderBottom: `1px solid ${c.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "700", fontSize: "16px" }}>Settings</span>
              <button onClick={() => setShowSettings(false)} style={{ background: c.bg3, border: "none", cursor: "pointer", fontSize: "14px", color: c.text2, width: "26px", height: "26px", borderRadius: "50%" }}>✕</button>
            </div>
            <div style={{ padding: "22px" }}>
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "14px", textTransform: "uppercase", letterSpacing: "1px" }}>Appearance</p>

              <div style={{ marginBottom: "22px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "3px" }}>Theme</p>
                  <p style={{ fontSize: "12px", color: c.text2 }}>Interface color</p>
                </div>
                <div style={{ display: "flex", gap: "3px", background: c.bg3, borderRadius: "8px", padding: "3px" }}>
                  {[{ v: "light", icon: "☀️" }, { v: "system", icon: "💻" }, { v: "dark", icon: "🌙" }].map(t => (
                    <button key={t.v} onClick={() => setTheme(t.v)} style={{
                      padding: "5px 10px", border: "none", borderRadius: "6px", cursor: "pointer",
                      background: theme === t.v ? (isDark ? "#555" : "#fff") : "transparent",
                      fontSize: "15px", boxShadow: theme === t.v ? "0 1px 3px rgba(0,0,0,0.15)" : "none",
                    }}>{t.icon}</button>
                  ))}
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "3px" }}>Font</p>
                  <p style={{ fontSize: "12px", color: c.text2 }}>Chat font style</p>
                </div>
                <select value={font} onChange={e => setFont(e.target.value)} style={{
                  background: c.bg3, border: `1px solid ${c.border}`, color: c.text,
                  padding: "7px 10px", borderRadius: "7px", fontSize: "13px", outline: "none",
                }}>
                  {FONTS.map(f => <option key={f.label} value={f.value}>{f.label}</option>)}
                </select>
              </div>

              <hr style={{ border: "none", borderTop: `1px solid ${c.border}`, margin: "18px 0" }} />
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "10px", textTransform: "uppercase", letterSpacing: "1px" }}>About</p>
              <div style={{ fontSize: "13px", color: c.text2, lineHeight: "2" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 Smart Sales Analytics</p>
                <p>⚡ FastAPI + Claude AI</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; background: white; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-5px)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }
        textarea::placeholder { color: #aaa; }
      `}</style>
    </div>
  )
}

export default App