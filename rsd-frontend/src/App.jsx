import { useState, useRef, useEffect } from "react"

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

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
      background: "#212121",
      color: "#ececec",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: "16px 20px",
        borderBottom: "1px solid #333",
        display: "flex",
        alignItems: "center",
        gap: "10px",
        background: "#212121",
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}>
        <span style={{ fontSize: "24px" }}>🤖</span>
        <span style={{ fontWeight: "600", fontSize: "18px" }}>RSD Enterprise AI</span>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "20px 0",
      }}>
        {messages.length === 0 && (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            gap: "12px",
            opacity: 0.5,
            paddingTop: "60px",
          }}>
            <span style={{ fontSize: "48px" }}>🤖</span>
            <p style={{ fontSize: "20px", fontWeight: "600" }}>RSD Enterprise AI</p>
            <p style={{ fontSize: "14px" }}>Sales data ke baare mein kuch bhi poochho!</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} style={{
            padding: "8px 0",
            background: m.role === "assistant" ? "#2a2a2a" : "transparent",
          }}>
            <div style={{
              maxWidth: "760px",
              margin: "0 auto",
              padding: "12px 20px",
              display: "flex",
              gap: "12px",
              alignItems: "flex-start",
            }}>
              {/* Avatar */}
              <div style={{
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: m.role === "user" ? "#7c3aed" : "#e05d26",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "14px",
                flexShrink: 0,
              }}>
                {m.role === "user" ? "👤" : "🤖"}
              </div>

              {/* Content */}
              <div style={{ flex: 1, paddingTop: "4px", lineHeight: "1.6", fontSize: "15px" }}>
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
          <div style={{ background: "#2a2a2a", padding: "8px 0" }}>
            <div style={{
              maxWidth: "760px",
              margin: "0 auto",
              padding: "12px 20px",
              display: "flex",
              gap: "12px",
              alignItems: "center",
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
                    background: "#888",
                    animation: "bounce 1.2s infinite",
                    animationDelay: `${i * 0.2}s`,
                  }} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div style={{
        padding: "16px 20px",
        background: "#212121",
        borderTop: "1px solid #333",
      }}>
        <div style={{
          maxWidth: "760px",
          margin: "0 auto",
          background: "#2f2f2f",
          borderRadius: "16px",
          border: "1px solid #444",
          display: "flex",
          alignItems: "flex-end",
          gap: "8px",
          padding: "10px 14px",
        }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Sawaal likho ya mic dabao..."
            rows={1}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "#ececec",
              fontSize: "15px",
              resize: "none",
              lineHeight: "1.5",
              maxHeight: "200px",
              overflowY: "auto",
              fontFamily: "inherit",
            }}
          />
          <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
            <button
              onClick={startVoice}
              style={{
                background: listening ? "#ff4444" : "transparent",
                border: "none",
                borderRadius: "8px",
                padding: "6px 8px",
                cursor: "pointer",
                fontSize: "18px",
                color: listening ? "white" : "#888",
                transition: "all 0.2s",
              }}
            >
              {listening ? "🔴" : "🎤"}
            </button>
            <button
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              style={{
                background: input.trim() && !loading ? "#e05d26" : "#444",
                border: "none",
                borderRadius: "8px",
                padding: "8px 12px",
                cursor: input.trim() && !loading ? "pointer" : "default",
                color: "white",
                fontSize: "16px",
                transition: "all 0.2s",
              }}
            >
              ➤
            </button>
          </div>
        </div>
        <p style={{ textAlign: "center", fontSize: "11px", color: "#555", marginTop: "8px" }}>
          Enter = Send • Shift+Enter = New line
        </p>
      </div>

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