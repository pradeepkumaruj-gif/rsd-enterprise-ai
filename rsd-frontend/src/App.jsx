import { useState, useRef, useEffect } from "react"

const FONTS = [
  { label: "Default", value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  { label: "Serif", value: "Georgia, 'Times New Roman', serif" },
  { label: "Mono", value: "'Courier New', Courier, monospace" },
  { label: "Roboto", value: "Roboto, Arial, sans-serif" },
]

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [theme, setTheme] = useState("dark") // dark | light | system
  const [font, setFont] = useState(FONTS[0].value)
  const recognitionRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  // System theme detection
  const getEffectiveTheme = () => {
    if (theme === "system") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
    }
    return theme
  }

  const isDark = getEffectiveTheme() === "dark"

  const colors = {
    bg: isDark ? "#212121" : "#ffffff",
    bg2: isDark ? "#2a2a2a" : "#f5f5f5",
    bg3: isDark ? "#2f2f2f" : "#ececec",
    border: isDark ? "#333" : "#ddd",
    text: isDark ? "#ececec" : "#1a1a1a",
    text2: isDark ? "#aaa" : "#666",
    input: isDark ? "#2f2f2f" : "#f0f0f0",
    userBubble: "#7c3aed",
    aiBubble: isDark ? "#2a2a2a" : "#f0f0f0",
    aiText: isDark ? "#ececec" : "#1a1a1a",
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  const startVoice = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) { alert("Voice support nahi hai!"); return }
    const recognition = new SpeechRecognition()
    recognition.lang = "hi-IN"
    recognition.onresult = (e) => setInput(e.results[0][0].transcript)
    recognition.onend = () => setListening(false)
    recognition.start()
    recognitionRef.current = recognition
    setListening(true)
  }

  const formatText = (text) => {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/^# (.*)/gm, '<h3 style="margin:8px 0">$1</h3>')
      .replace(/\n/g, '<br/>')
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const userMsg = { role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)
    if (textareaRef.current) textareaRef.current.style.height = "auto"
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 60000)
      const response = await fetch("https://rsd-enterprise-ai-production.up.railway.app/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input }),
        signal: controller.signal
      })
      clearTimeout(timeout)
      const data = await response.json()
      setMessages(prev => [...prev, { role: "assistant", content: data.reply }])
    } catch (error) {
      console.error("API Error:", error)
      setMessages(prev => [...prev, { role: "assistant", content: "❌ Error! Dobara try karo." }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleInput = (e) => {
    setInput(e.target.value)
    e.target.style.height = "auto"
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px"
  }

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      background: colors.bg,
      color: colors.text,
      fontFamily: font,
      transition: "all 0.2s",
    }}>
      {/* Header */}
      <div style={{
        padding: "14px 20px",
        borderBottom: `1px solid ${colors.border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: colors.bg,
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "22px" }}>🤖</span>
          <span style={{ fontWeight: "600", fontSize: "17px" }}>RSD Enterprise AI</span>
        </div>
        <button
          onClick={() => setShowSettings(true)}
          style={{
            background: "transparent",
            border: "none",
            cursor: "pointer",
            fontSize: "20px",
            color: colors.text2,
            padding: "6px",
            borderRadius: "8px",
          }}
          title="Settings"
        >
          ⚙️
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 0" }}>
        {messages.length === 0 && (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", height: "100%", gap: "12px",
            opacity: 0.4, paddingTop: "60px",
          }}>
            <span style={{ fontSize: "48px" }}>🤖</span>
            <p style={{ fontSize: "20px", fontWeight: "600" }}>RSD Enterprise AI</p>
            <p style={{ fontSize: "14px" }}>Sales data ke baare mein kuch bhi poochho!</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} style={{
            padding: "8px 0",
            background: m.role === "assistant" ? colors.bg2 : "transparent",
          }}>
            <div style={{
              maxWidth: "760px", margin: "0 auto", padding: "12px 20px",
              display: "flex", gap: "12px", alignItems: "flex-start",
            }}>
              <div style={{
                width: "32px", height: "32px", borderRadius: "50%",
                background: m.role === "user" ? "#7c3aed" : "#e05d26",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "14px", flexShrink: 0,
              }}>
                {m.role === "user" ? "👤" : "🤖"}
              </div>
              <div style={{ flex: 1, paddingTop: "4px", lineHeight: "1.6", fontSize: "15px", color: colors.text }}>
                {m.role === "assistant" ? (
                  <div dangerouslySetInnerHTML={{ __html: formatText(m.content) }} />
                ) : (
                  <div>{m.content}</div>
                )}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ background: colors.bg2, padding: "8px 0" }}>
            <div style={{
              maxWidth: "760px", margin: "0 auto", padding: "12px 20px",
              display: "flex", gap: "12px", alignItems: "center",
            }}>
              <div style={{
                width: "32px", height: "32px", borderRadius: "50%",
                background: "#e05d26", display: "flex",
                alignItems: "center", justifyContent: "center", fontSize: "14px",
              }}>🤖</div>
              <div style={{ display: "flex", gap: "4px", paddingTop: "4px" }}>
                {[0,1,2].map(i => (
                  <div key={i} style={{
                    width: "8px", height: "8px", borderRadius: "50%",
                    background: "#888", animation: "bounce 1.2s infinite",
                    animationDelay: `${i * 0.2}s`,
                  }} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "16px 20px", background: colors.bg, borderTop: `1px solid ${colors.border}` }}>
        <div style={{
          maxWidth: "760px", margin: "0 auto",
          background: colors.input, borderRadius: "16px",
          border: `1px solid ${colors.border}`,
          display: "flex", alignItems: "flex-end", gap: "8px", padding: "10px 14px",
        }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Sawaal likho ya mic dabao..."
            rows={1}
            style={{
              flex: 1, background: "transparent", border: "none", outline: "none",
              color: colors.text, fontSize: "15px", resize: "none",
              lineHeight: "1.5", maxHeight: "200px", overflowY: "auto", fontFamily: font,
            }}
          />
          <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
            <button onClick={startVoice} style={{
              background: listening ? "#ff4444" : "transparent", border: "none",
              borderRadius: "8px", padding: "6px 8px", cursor: "pointer",
              fontSize: "18px", color: listening ? "white" : "#888",
            }}>
              {listening ? "🔴" : "🎤"}
            </button>
            <button onClick={sendMessage} disabled={!input.trim() || loading} style={{
              background: input.trim() && !loading ? "#e05d26" : "#888",
              border: "none", borderRadius: "8px", padding: "8px 12px",
              cursor: input.trim() && !loading ? "pointer" : "default",
              color: "white", fontSize: "16px",
            }}>➤</button>
          </div>
        </div>
        <p style={{ textAlign: "center", fontSize: "11px", color: colors.text2, marginTop: "8px" }}>
          Enter = Send • Shift+Enter = New line
        </p>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center",
          padding: "20px",
        }} onClick={() => setShowSettings(false)}>
          <div style={{
            background: colors.bg, borderRadius: "16px", width: "100%", maxWidth: "500px",
            maxHeight: "80vh", overflowY: "auto",
            border: `1px solid ${colors.border}`, boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          }} onClick={e => e.stopPropagation()}>
            
            {/* Modal Header */}
            <div style={{
              padding: "20px 24px", borderBottom: `1px solid ${colors.border}`,
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span style={{ fontWeight: "600", fontSize: "18px" }}>⚙️ Settings</span>
              <button onClick={() => setShowSettings(false)} style={{
                background: "transparent", border: "none", cursor: "pointer",
                fontSize: "20px", color: colors.text2,
              }}>✕</button>
            </div>

            {/* Settings Content */}
            <div style={{ padding: "24px" }}>
              
              {/* Appearance Section */}
              <p style={{ fontWeight: "600", fontSize: "13px", color: colors.text2, marginBottom: "16px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Appearance
              </p>

              {/* Theme */}
              <div style={{ marginBottom: "24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <p style={{ fontWeight: "500", marginBottom: "4px" }}>Theme</p>
                    <p style={{ fontSize: "13px", color: colors.text2 }}>App ka color theme choose karo</p>
                  </div>
                  <div style={{ display: "flex", gap: "4px", background: colors.bg3, borderRadius: "8px", padding: "3px" }}>
                    {[
                      { value: "light", icon: "☀️", label: "Light" },
                      { value: "system", icon: "💻", label: "System" },
                      { value: "dark", icon: "🌙", label: "Dark" },
                    ].map(t => (
                      <button key={t.value} onClick={() => setTheme(t.value)} style={{
                        padding: "6px 12px", border: "none", borderRadius: "6px", cursor: "pointer",
                        background: theme === t.value ? (isDark ? "#444" : "#fff") : "transparent",
                        color: colors.text, fontSize: "13px", fontWeight: theme === t.value ? "600" : "400",
                        boxShadow: theme === t.value ? "0 1px 4px rgba(0,0,0,0.2)" : "none",
                        transition: "all 0.15s",
                      }}>
                        {t.icon}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Font */}
              <div style={{ marginBottom: "24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <p style={{ fontWeight: "500", marginBottom: "4px" }}>Chat Font</p>
                    <p style={{ fontSize: "13px", color: colors.text2 }}>Message ka font choose karo</p>
                  </div>
                  <select
                    value={font}
                    onChange={e => setFont(e.target.value)}
                    style={{
                      background: colors.bg3, border: `1px solid ${colors.border}`,
                      color: colors.text, padding: "8px 12px", borderRadius: "8px",
                      fontSize: "14px", cursor: "pointer", outline: "none",
                    }}
                  >
                    {FONTS.map(f => (
                      <option key={f.label} value={f.value}>{f.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <hr style={{ border: "none", borderTop: `1px solid ${colors.border}`, margin: "20px 0" }} />

              {/* About Section */}
              <p style={{ fontWeight: "600", fontSize: "13px", color: colors.text2, marginBottom: "16px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                About
              </p>
              <div style={{ fontSize: "14px", color: colors.text2, lineHeight: "1.8" }}>
                <p>🤖 RSD Enterprise AI</p>
                <p>📊 Data: 2,214 sales records</p>
                <p>⚡ Backend: FastAPI + Claude AI</p>
                <p>🚀 Deployed on Railway</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { margin: 0; }
        @keyframes bounce {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-6px); }
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #444; border-radius: 3px; }
      `}</style>
    </div>
  )
}

export default App
