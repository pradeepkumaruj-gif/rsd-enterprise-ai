import { useState, useRef, useEffect } from "react"
import { Send, Plus, Menu, Sun, Moon, MessageSquare, Mic, MicOff, Copy, Check, Trash2, Settings, X } from "lucide-react"

let chatId = 1

export default function RSDEnterpriseAI() {
  const [darkMode, setDarkMode] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 768)
  const [chats, setChats] = useState([{ id: 1, title: "New conversation", messages: [] }])
  const [activeChatId, setActiveChatId] = useState(1)
  const [input, setInput] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [copiedId, setCopiedId] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  const recognitionRef = useRef(null)
  const streamIntervalRef = useRef(null)

  const activeChat = chats.find(c => c.id === activeChatId)
  const messages = activeChat?.messages || []

  // Colors
  const accent = "#D97757"
  const bg = darkMode ? "#212121" : "#ffffff"
  const sidebarBg = darkMode ? "#181818" : "#f4f4f4"
  const text = darkMode ? "#ececec" : "#1a1a1a"
  const subText = darkMode ? "#888" : "#666"
  const border = darkMode ? "#2e2e2e" : "#e5e5e5"
  const inputBg = darkMode ? "#2f2f2f" : "#f9f9f9"
  const userBubble = darkMode ? "#2f2f2f" : "#f0f0f0"
  const hoverBg = darkMode ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)"

  // Auto scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages, isTyping])

  // Auto resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + "px"
    }
  }, [input])

  // Voice setup
  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    const r = new SR()
    r.continuous = false
    r.interimResults = true
    r.lang = "hi-IN"
    r.onresult = (e) => setInput(Array.from(e.results).map(x => x[0].transcript).join(""))
    r.onend = () => setIsListening(false)
    r.onerror = () => setIsListening(false)
    recognitionRef.current = r
  }, [])

  function toggleMic() {
    if (!recognitionRef.current) { alert("Voice not supported!"); return }
    if (isListening) { recognitionRef.current.stop(); setIsListening(false) }
    else { recognitionRef.current.start(); setIsListening(true) }
  }

  function newChat() {
    chatId++
    const c = { id: chatId, title: "New conversation", messages: [] }
    setChats(prev => [c, ...prev])
    setActiveChatId(chatId)
    setInput("")
    if (window.innerWidth < 768) setSidebarOpen(false)
  }

  function deleteChat(id, e) {
    e.stopPropagation()
    setChats(prev => {
      const remaining = prev.filter(c => c.id !== id)
      if (remaining.length === 0) { newChat(); return prev }
      if (activeChatId === id) setActiveChatId(remaining[0].id)
      return remaining
    })
  }

  function copyText(text, id) {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  // Stream response word by word
  function streamReply(fullText) {
    setIsTyping(true)
    const words = fullText.split(" ")
    let idx = 0
    // Add empty assistant message
    setChats(prev => prev.map(c =>
      c.id !== activeChatId ? c : { ...c, messages: [...c.messages, { id: Date.now(), role: "assistant", text: "" }] }
    ))
    if (streamIntervalRef.current) clearInterval(streamIntervalRef.current)
    streamIntervalRef.current = setInterval(() => {
      if (idx < words.length) {
        const word = words[idx]
        setChats(prev => prev.map(c => {
          if (c.id !== activeChatId) return c
          const msgs = [...c.messages]
          msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], text: msgs[msgs.length - 1].text + (idx === 0 ? "" : " ") + word }
          return { ...c, messages: msgs }
        }))
        idx++
      } else {
        clearInterval(streamIntervalRef.current)
        setIsTyping(false)
      }
    }, 18)
  }

  async function handleSend() {
    if (!input.trim() || isTyping) return
    const msgText = input
    setInput("")

    // Add user message
    setChats(prev => prev.map(c => {
      if (c.id !== activeChatId) return c
      const isFirst = c.messages.length === 0
      return {
        ...c,
        title: isFirst ? msgText.slice(0, 32) + (msgText.length > 32 ? "..." : "") : c.title,
        messages: [...c.messages, { id: Date.now(), role: "user", text: msgText }]
      }
    }))

    if (window.innerWidth < 768) setSidebarOpen(false)

    try {
      const res = await fetch("https://rsd-enterprise-ai-production.up.railway.app/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msgText })
      })
      const data = await res.json()
      streamReply(data.reply)
    } catch {
      streamReply("❌ Error! Backend se connect nahi ho pa raha. Dobara try karo.")
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // Format AI response
  function formatText(text) {
    if (!text) return ""
    return text
      .replace(/---+/g, "")
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.*?)\*/g, "<em>$1</em>")
      .replace(/^### (.*)/gm, `<div style="font-size:15px;font-weight:700;margin:12px 0 4px">$1</div>`)
      .replace(/^## (.*)/gm, `<div style="font-size:16px;font-weight:700;margin:14px 0 6px">$1</div>`)
      .replace(/^# (.*)/gm, `<div style="font-size:18px;font-weight:700;margin:16px 0 8px">$1</div>`)
      .replace(/^[-•] (.*)/gm, `<div style="display:flex;gap:8px;margin:2px 0;padding-left:8px"><span style="margin-top:8px;width:4px;height:4px;border-radius:50%;background:#888;flex-shrink:0"></span><span>$1</span></div>`)
      .replace(/`(.*?)`/g, `<code style="background:${darkMode ? "#333" : "#f0f0f0"};padding:2px 6px;border-radius:4px;font-size:13px;font-family:monospace">$1</code>`)
      .replace(/\n/g, "<br/>")
  }

  return (
    <div style={{ display: "flex", height: "100vh", width: "100%", background: bg, color: text, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", overflow: "hidden" }}>

      {/* Mobile overlay */}
      {sidebarOpen && window.innerWidth < 768 && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 40 }} />
      )}

      {/* SIDEBAR */}
      <div style={{
        width: sidebarOpen ? "260px" : "0",
        minWidth: sidebarOpen ? "260px" : "0",
        background: sidebarBg,
        borderRight: sidebarOpen ? `1px solid ${border}` : "none",
        overflow: "hidden",
        transition: "all 0.2s ease",
        display: "flex", flexDirection: "column",
        height: "100vh",
        position: window.innerWidth < 768 ? "fixed" : "relative",
        zIndex: 50,
      }}>
        {/* New chat button */}
        <div style={{ padding: "12px" }}>
          <button onClick={newChat} style={{
            width: "100%", padding: "9px 12px", background: "transparent",
            border: `1px solid ${border}`, borderRadius: "8px", color: text,
            cursor: "pointer", fontSize: "13px", fontWeight: "500",
            display: "flex", alignItems: "center", gap: "8px",
            transition: "background 0.15s",
          }}
            onMouseEnter={e => e.currentTarget.style.background = hoverBg}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >
            <Plus size={15} />
            New chat
          </button>
        </div>

        {/* Chat list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
          <p style={{ fontSize: "11px", color: subText, padding: "6px 8px", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: "600" }}>Recents</p>
          {chats.map(c => (
            <div key={c.id} onClick={() => { setActiveChatId(c.id); if (window.innerWidth < 768) setSidebarOpen(false) }}
              style={{
                display: "flex", alignItems: "center", gap: "8px",
                padding: "8px 10px", borderRadius: "6px", cursor: "pointer",
                marginBottom: "1px",
                background: c.id === activeChatId ? (darkMode ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.07)") : "transparent",
                transition: "background 0.1s",
              }}
              onMouseEnter={e => { if (c.id !== activeChatId) e.currentTarget.style.background = hoverBg }}
              onMouseLeave={e => { if (c.id !== activeChatId) e.currentTarget.style.background = "transparent" }}
            >
              <MessageSquare size={13} color={subText} style={{ flexShrink: 0 }} />
              <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{c.title}</span>
              <button onClick={(e) => deleteChat(c.id, e)} style={{
                background: "transparent", border: "none", cursor: "pointer",
                color: subText, padding: "2px", opacity: 0, flexShrink: 0,
                display: "flex", alignItems: "center",
              }}
                onMouseEnter={e => e.currentTarget.style.opacity = 1}
                onMouseLeave={e => e.currentTarget.style.opacity = 0}
              ><Trash2 size={12} /></button>
            </div>
          ))}
        </div>

        {/* Bottom — User + Theme */}
        <div style={{ padding: "10px 12px", borderTop: `1px solid ${border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div style={{
              width: "28px", height: "28px", borderRadius: "50%",
              background: accent, display: "flex", alignItems: "center",
              justifyContent: "center", fontSize: "12px", fontWeight: "700", color: "white", flexShrink: 0,
            }}>R</div>
            <span style={{ fontSize: "13px", fontWeight: "500" }}>RSD AI</span>
          </div>
          <div style={{ display: "flex", gap: "4px" }}>
            <button onClick={() => setShowSettings(true)} style={{
              background: "transparent", border: "none", cursor: "pointer",
              padding: "6px", borderRadius: "6px", color: subText,
              display: "flex", alignItems: "center",
            }}
              onMouseEnter={e => e.currentTarget.style.background = hoverBg}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            ><Settings size={15} /></button>
            <button onClick={() => setDarkMode(d => !d)} style={{
              background: "transparent", border: "none", cursor: "pointer",
              padding: "6px", borderRadius: "6px", color: subText,
              display: "flex", alignItems: "center",
            }}
              onMouseEnter={e => e.currentTarget.style.background = hoverBg}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >{darkMode ? <Sun size={15} /> : <Moon size={15} />}</button>
          </div>
        </div>
      </div>

      {/* MAIN AREA */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 16px", borderBottom: `1px solid ${border}`, flexShrink: 0 }}>
          <button onClick={() => setSidebarOpen(s => !s)} style={{
            background: "transparent", border: "none", cursor: "pointer",
            padding: "6px", borderRadius: "6px", color: subText,
            display: "flex", alignItems: "center",
          }}
            onMouseEnter={e => e.currentTarget.style.background = hoverBg}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          ><Menu size={17} /></button>
          <span style={{ fontSize: "14px", fontWeight: "500", color: subText }}>
            {activeChat?.title || "New conversation"}
          </span>
        </div>

        {/* Messages */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "0" }}>

          {/* Welcome */}
          {messages.length === 0 && (
            <div style={{ padding: "48px 24px 24px" }}>
              <p style={{ fontSize: "22px", fontWeight: "600", marginBottom: "8px" }}>RSD Enterprise AI</p>
              <p style={{ fontSize: "14px", color: subText, marginBottom: "24px", lineHeight: "1.6" }}>
                Sales data ke baare mein kuch bhi poochho
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {["Top TSE kaun hai?", "Party wise month sale", "Total sales kitni?", "Brand performance"].map(q => (
                  <button key={q} onClick={() => setInput(q)} style={{
                    padding: "8px 16px", background: "transparent",
                    border: `1px solid ${border}`, borderRadius: "20px",
                    cursor: "pointer", fontSize: "13px", color: text,
                    transition: "all 0.15s",
                  }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = accent; e.currentTarget.style.color = accent }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = border; e.currentTarget.style.color = text }}
                  >{q}</button>
                ))}
              </div>
            </div>
          )}

          {/* Message list */}
          <div style={{ maxWidth: "760px", margin: "0 auto", padding: "16px 24px" }}>
            {messages.map((m, i) => (
              <div key={m.id || i} style={{ marginBottom: "24px" }}>
                {m.role === "user" ? (
                  // User bubble — RIGHT
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <div style={{
                      maxWidth: "75%", background: userBubble, color: text,
                      padding: "10px 16px", borderRadius: "18px 18px 4px 18px",
                      fontSize: "15px", lineHeight: "1.6", textAlign: "left",
                    }}>{m.text}</div>
                  </div>
                ) : (
                  // AI response — LEFT with avatar
                  <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                    <div style={{
                      width: "28px", height: "28px", borderRadius: "50%",
                      background: accent, flexShrink: 0, marginTop: "2px",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "11px", fontWeight: "700", color: "white",
                    }}>R</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "15px", lineHeight: "1.75", color: text, textAlign: "left" }}
                        dangerouslySetInnerHTML={{ __html: formatText(m.text) + (isTyping && i === messages.length - 1 ? `<span style="display:inline-block;width:2px;height:16px;background:${accent};margin-left:2px;animation:blink 1s infinite;vertical-align:text-bottom"></span>` : "") }} />
                      {!isTyping && (
                        <button onClick={() => copyText(m.text, m.id)} style={{
                          background: "transparent", border: "none", cursor: "pointer",
                          color: subText, padding: "4px 0", marginTop: "6px",
                          display: "flex", alignItems: "center", gap: "5px", fontSize: "12px",
                          opacity: 0.7, transition: "opacity 0.2s",
                        }}
                          onMouseEnter={e => e.currentTarget.style.opacity = 1}
                          onMouseLeave={e => e.currentTarget.style.opacity = 0.7}
                        >
                          {copiedId === m.id ? <><Check size={12} /> Copied!</> : <><Copy size={12} /> Copy</>}
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Loading dots */}
            {isTyping && messages.length === 0 && (
              <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: accent, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "11px", fontWeight: "700", color: "white" }}>R</div>
                <div style={{ display: "flex", gap: "4px" }}>
                  {[0,1,2].map(i => <div key={i} style={{ width: "6px", height: "6px", borderRadius: "50%", background: subText, animation: "bounce 1.2s infinite", animationDelay: `${i*0.15}s` }} />)}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Input */}
        <div style={{ padding: "12px 24px 20px", flexShrink: 0 }}>
          <div style={{ maxWidth: "760px", margin: "0 auto" }}>
            <div style={{
              display: "flex", alignItems: "flex-end", gap: "8px",
              background: inputBg, borderRadius: "14px",
              border: `1px solid ${border}`, padding: "10px 12px",
              boxShadow: darkMode ? "none" : "0 1px 8px rgba(0,0,0,0.06)",
            }}>
              <textarea ref={textareaRef} value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={isListening ? "Sun raha hoon..." : "Message RSD AI..."}
                rows={1}
                style={{
                  flex: 1, background: "transparent", border: "none", outline: "none",
                  color: text, fontSize: "15px", resize: "none", lineHeight: "1.5",
                  maxHeight: "200px", overflowY: "auto",
                  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                }}
              />
              <button onClick={toggleMic} style={{
                background: isListening ? accent : "transparent",
                border: "none", cursor: "pointer", padding: "7px",
                borderRadius: "8px", color: isListening ? "white" : subText,
                display: "flex", alignItems: "center", flexShrink: 0,
                transition: "all 0.2s",
              }}>
                {isListening ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
              <button onClick={handleSend} disabled={!input.trim() || isTyping} style={{
                background: input.trim() && !isTyping ? accent : (darkMode ? "#333" : "#e0e0e0"),
                border: "none", cursor: input.trim() ? "pointer" : "default",
                padding: "7px", borderRadius: "8px", color: "white",
                display: "flex", alignItems: "center", flexShrink: 0,
                transition: "all 0.2s",
                opacity: !input.trim() || isTyping ? 0.5 : 1,
              }}>
                <Send size={16} />
              </button>
            </div>
            <p style={{ textAlign: "center", fontSize: "11px", color: subText, marginTop: "8px" }}>
              RSD AI can make mistakes. Please verify important data.
            </p>
          </div>
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: "20px" }}
          onClick={() => setShowSettings(false)}>
          <div style={{ background: bg, borderRadius: "14px", width: "100%", maxWidth: "400px", border: `1px solid ${border}`, boxShadow: "0 20px 50px rgba(0,0,0,0.2)" }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: "600", fontSize: "15px" }}>Settings</span>
              <button onClick={() => setShowSettings(false)} style={{ background: "transparent", border: "none", cursor: "pointer", color: subText, display: "flex" }}><X size={18} /></button>
            </div>
            <div style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "3px" }}>Appearance</p>
                  <p style={{ fontSize: "12px", color: subText }}>Light ya Dark theme</p>
                </div>
                <button onClick={() => setDarkMode(d => !d)} style={{
                  display: "flex", alignItems: "center", gap: "8px",
                  background: darkMode ? "#333" : "#f0f0f0",
                  border: "none", borderRadius: "8px", padding: "8px 14px",
                  cursor: "pointer", color: text, fontSize: "13px", fontWeight: "500",
                }}>
                  {darkMode ? <><Sun size={14} /> Light</> : <><Moon size={14} /> Dark</>}
                </button>
              </div>
              <hr style={{ border: "none", borderTop: `1px solid ${border}`, margin: "16px 0" }} />
              <p style={{ fontWeight: "600", fontSize: "11px", color: subText, marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>About</p>
              <div style={{ fontSize: "13px", color: subText, lineHeight: "2" }}>
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
        body { margin: 0; }
        @keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-4px)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }
        textarea::placeholder { color: #aaa; }
      `}</style>
    </div>
  )
}