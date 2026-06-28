import { useState, useRef } from "react"

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef(null)

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
      .replace(/^# (.*)/gm, '<h3>$1</h3>')
      .replace(/\n/g, '<br/>')
  }

  const sendMessage = async () => {
    if (!input.trim()) return
    const userMsg = { role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)
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

  return (
    <div style={{ maxWidth: "700px", margin: "40px auto", fontFamily: "sans-serif" }}>
      <h1>🤖 RSD Enterprise AI</h1>
      <div style={{ height: "400px", overflowY: "auto", border: "1px solid #ccc", padding: "10px", borderRadius: "8px", marginBottom: "10px", background: "#111" }}>
        {messages.map((m, i) => (
          <div key={i} style={{ textAlign: m.role === "user" ? "right" : "left", margin: "8px 0" }}>
            {m.role === "assistant" ? (
              <span style={{ background: "#f0f0f0", color: "black", padding: "8px 12px", borderRadius: "12px", display: "inline-block", textAlign: "left" }}
                dangerouslySetInnerHTML={{ __html: formatText(m.content) }} />
            ) : (
              <span style={{ background: "#007bff", color: "white", padding: "8px 12px", borderRadius: "12px", display: "inline-block" }}>
                {m.content}
              </span>
            )}
          </div>
        ))}
        {loading && <div style={{color:"white"}}>🤖 Soch raha hoon...</div>}
      </div>
      <div style={{ display: "flex", gap: "8px" }}>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && sendMessage()} placeholder="Sawaal likho ya mic dabao..." style={{ flex: 1, padding: "10px", borderRadius: "8px", border: "1px solid #ccc" }} />
        <button onClick={startVoice} style={{ padding: "10px 16px", background: listening ? "#ff4444" : "#28a745", color: "white", border: "none", borderRadius: "8px", cursor: "pointer", fontSize: "18px" }}>
          {listening ? "🔴" : "🎤"}
        </button>
        <button onClick={sendMessage} style={{ padding: "10px 20px", background: "#007bff", color: "white", border: "none", borderRadius: "8px", cursor: "pointer" }}>Send</button>
      </div>
    </div>
  )
}

export default App