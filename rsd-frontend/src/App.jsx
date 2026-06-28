import { useState, useRef, useEffect } from "react"

const FONTS = [
  { label: "Default", value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  { label: "Serif", value: "Georgia, 'Times New Roman', serif" },
  { label: "Mono", value: "'Courier New', Courier, monospace" },
  { label: "Roboto", value: "Roboto, Arial, sans-serif" },
]

let chatIdCounter = 1

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
    userDot: "#7c3aed",
    aiDot: "#e05d26",
  }

  const activeChat = chats.find(ch => ch.id === activeChatId)
  const messages = activeChat?.messages || []

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  const newChat = () => {
    chatIdCounter++
    const newC = { id: chatIdCounter, title: "Naya Sawaal", messages: [] }
    setChats(prev => [newC, ...prev])
    setActiveChatId(chatIdCounter)
    setInput("")
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

  const formatText = (text) => text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/^## (.*)/gm, '<h3 style="margin:12px 0 6px;font-size:16px">$1</h3>')
    .replace(/^# (.*)/gm, '<h2 style="margin:14px 0 8px;font-size:18px">$1</h2>')
    .replace(/^- (.*)/gm, '<div style="margin:4px 0;padding-left:16px">• $1</div>')
    .replace(/\n\n/g, '<br/>')

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const userMsg = { role: "user", content: input }
    const msgText = input
    setInput("")
    if (textareaRef.current) textareaRef.current.style.height = "auto"
    setLoading(true)

    setChats(prev => prev.map(ch => {
      if (ch.id !== activeChatId) return ch
      const isFirst = ch.messages.length === 0
      return {
        ...ch,
        title: isFirst ? msgText.slice(0, 28) + (msgText.length > 28 ? "..." : "") : ch.title,
        messages: [...ch.messages, userMsg]
      }
    }))

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
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : { ...ch, messages: [...ch.messages, { role: "assistant", content: data.reply }] }
      ))
    } catch (error) {
      setChats(prev => prev.map(ch =>
        ch.id !== activeChatId ? ch : { ...ch, messages: [...ch.messages, { role: "assistant", content: "❌ Error! Dobara try karo." }] }
      ))
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

      {/* Sidebar */}
      {sidebarOpen && (
        <div style={{
          width: "260px", minWidth: "260px",
          background: c.sidebar,
          borderRight: `1px solid ${c.border}`,
          display: "flex", flexDirection: "column",
          height: "100vh", overflow: "hidden",
        }}>
          <div style={{ padding: "16px 12px", borderBottom: `1px solid ${c.border}` }}>
            <button onClick={newChat} style={{
              width: "100%", padding: "10px 14px",
              background: isDark ? "#2a2a2a" : "#f5f5f5",
              border: `1px solid ${c.border}`,
              borderRadius: "10px", color: c.text, cursor: "pointer",
              fontSize: "14px", fontWeight: "500",
              display: "flex", alignItems: "center", gap: "8px",
            }}>
              ✏️ Naya Chat
            </button>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
            <p style={{ fontSize: "11px", color: c.text2, padding: "8px 8px 4px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Chat History
            </p>
            {chats.map(ch => (
              <div key={ch.id} onClick={() => setActiveChatId(ch.id)}
                style={{
                  padding: "10px 12px", borderRadius: "8px", cursor: "pointer", marginBottom: "2px",
                  background: ch.id === activeChatId ? c.active : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
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
                }}>🗑️</button>
              </div>
            ))}
          </div>

          <div style={{ padding: "12px", borderTop: `1px solid ${c.border}` }}>
            <button onClick={() => setShowSettings(true)} style={{
              width: "100%", padding: "10px 14px", background: "transparent",
              border: "none", borderRadius: "8px", color: c.text2, cursor: "pointer",
              fontSize: "13px", display: "flex", alignItems: "center", gap: "8px",
            }}>
              ⚙️ Settings
            </button>
          </div>
        </div>
      )}

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: c.bg }}>

        {/* Header */}
        <div style={{
          padding: "14px 20px", borderBottom: `1px solid ${c.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: c.bg, flexShrink: 0,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} style={{
              background: "transparent", border: "none", cursor: "pointer",
              fontSize: "18px", color: c.text2, padding: "4px",
            }}>☰</button>
            <span style={{ fontWeight: "600", fontSize: "16px" }}>🤖 RSD Enterprise AI</span>
          </div>
          <button onClick={() => setShowSettings(true)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            fontSize: "18px", color: c.text2,
          }}>⚙️</button>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0" }}>
          {messages.length === 0 && (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%", gap: "12px", opacity: 0.4,
            }}>
              <span style={{ fontSize: "48px" }}>🤖</span>
              <p style={{ fontSize: "20px", fontWeight: "600" }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px" }}>Sales data ke baare mein kuch bhi poochho!</p>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} style={{
              padding: "20px 0",
              background: m.role === "assistant" ? c.bg2 : c.bg,
              borderBottom: `1px solid ${c.border}`,
            }}>
              <div style={{
                maxWidth: "720px", margin: "0 auto", padding: "0 24px",
                display: "flex", gap: "14px", alignItems: "flex-start",
              }}>
                {/* Avatar — sirf colored dot, no icon */}
                <div style={{
                  width: "28px", height: "28px", borderRadius: "50%",
                  background: m.role === "user" ? c.userDot : c.aiDot,
                  flexShrink: 0, marginTop: "2px",
                }} />
                {/* Text — LEFT aligned */}
                <div style={{
                  flex: 1, lineHeight: "1.7", fontSize: "15px", color: c.text,
                  textAlign: "left",
                }}>
                  <p style={{ fontWeight: "600", fontSize: "13px", color: c.text2, marginBottom: "6px" }}>
                    {m.role === "user" ? "Aap" : "RSD AI"}
                  </p>
                  {m.role === "assistant"
                    ? <div dangerouslySetInnerHTML={{ __html: formatText(m.content) }} />
                    : <div>{m.content}</div>}
                </div>
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ padding: "20px 0", background: c.bg2, borderBottom: `1px solid ${c.border}` }}>
              <div style={{ maxWidth: "720px", margin: "0 auto", padding: "0 24px", display: "flex", gap: "14px", alignItems: "center" }}>
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: c.aiDot, flexShrink: 0 }} />
                <div>
                  <p style={{ fontWeight: "600", fontSize: "13px", color: c.text2, marginBottom: "8px" }}>RSD AI</p>
                  <div style={{ display: "flex", gap: "4px" }}>
                    {[0,1,2].map(i => (
                      <div key={i} style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#888", animation: "bounce 1.2s infinite", animationDelay: `${i*0.2}s` }} />
                    ))}
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
            maxWidth: "720px", margin: "0 auto",
            background: c.bg3, borderRadius: "16px",
            border: `1px solid ${c.border}`,
            display: "flex", alignItems: "flex-end", gap: "8px", padding: "10px 14px",
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
                fontSize: "18px", color: listening ? "white" : "#888",
              }}>{listening ? "🔴" : "🎤"}</button>
              <button onClick={sendMessage} disabled={!input.trim() || loading} style={{
                background: input.trim() && !loading ? "#e05d26" : "#ccc",
                border: "none", borderRadius: "8px", padding: "8px 12px",
                cursor: input.trim() && !loading ? "pointer" : "default",
                color: "white", fontSize: "16px",
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
          <div style={{ background: c.bg, borderRadius: "16px", width: "100%", maxWidth: "480px", maxHeight: "80vh", overflowY: "auto", border: `1px solid ${c.border}`, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "20px 24px", borderBottom: `1px solid ${c.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "600", fontSize: "17px" }}>⚙️ Settings</span>
              <button onClick={() => setShowSettings(false)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "20px", color: c.text2 }}>✕</button>
            </div>
            <div style={{ padding: "24px" }}>
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "16px", textTransform: "uppercase", letterSpacing: "0.8px" }}>Appearance</p>
              
              <div style={{ marginBottom: "24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "4px" }}>Theme</p>
                  <p style={{ fontSize: "13px", color: c.text2 }}>Color theme choose karo</p>
                </div>
                <div style={{ display: "flex", gap: "4px", background: c.bg3, borderRadius: "8px", padding: "3px" }}>
                  {[{ value: "light", icon: "☀️" }, { value: "system", icon: "💻" }, { value: "dark", icon: "🌙" }].map(t => (
                    <button key={t.value} onClick={() => setTheme(t.value)} style={{
                      padding: "6px 12px", border: "none", borderRadius: "6px", cursor: "pointer",
                      background: theme === t.value ? (isDark ? "#444" : "#fff") : "transparent",
                      color: c.text, fontSize: "16px",
                      boxShadow: theme === t.value ? "0 1px 4px rgba(0,0,0,0.15)" : "none",
                    }}>{t.icon}</button>
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
              <p style={{ fontWeight: "600", fontSize: "11px", color: c.text2, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.8px" }}>About</p>
              <div style={{ fontSize: "14px", color: c.text2, lineHeight: "2" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 2,214 sales records</p>
                <p>⚡ FastAPI + Claude AI</p>
                <p>🚀 Deployed on Railway</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-6px)} }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
      `}</style>
    </div>
  )
}

export default App
