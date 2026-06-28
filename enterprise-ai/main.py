from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import os
import pandas as pd


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
df = pd.read_csv(os.path.join(os.path.dirname(__file__), 'RSD 3.csv'))
df.columns = df.columns.str.strip()

# Naye column names
tse_cols = ['Sale-Barent Qty', 'Sale-Royal Ace Qty', 'Sale-Dennis Gold Qty', 'Sale-BL GA Qty', 'Sale-BL Pure Qty', 'Sale-CNC RUM Qty']
df['Total'] = df[tse_cols].sum(axis=1)

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def home():
    return {"message": "RSD Enterprise AI Ready! 🚀"}

@app.post("/chat")
def chat(request: ChatRequest):
    question = request.message.lower()
    
    if 'top tse' in question or 'best tse' in question:
        result = df.groupby('TSE/Sales Man Name')['Total'].sum().sort_values(ascending=False).head(3)
        data = f"Top 3 TSE:\n{result.to_string()}"
    elif 'tse' in question or 'sab tse' in question or 'all tse' in question or 'sales man' in question:
        result = df.groupby('TSE/Sales Man Name')['Total'].sum().sort_values(ascending=False)
        data = f"All TSE Performance:\n{result.to_string()}"
    elif 'dept' in question or 'department' in question or 'vibhag' in question:
        result = df.groupby('Department')['Total'].sum().sort_values(ascending=False)
        data = f"Department Sales:\n{result.to_string()}"
    elif 'top party' in question or 'best party' in question:
        result = df.groupby('Party Name')['Total'].sum().sort_values(ascending=False).head(5)
        data = f"Top 5 Parties:\n{result.to_string()}"
    elif 'party' in question:
        result = df.groupby('Party Name')['Total'].sum().sort_values(ascending=False).head(10)
        data = f"Top 10 Parties:\n{result.to_string()}"
    elif 'month' in question or 'mahina' in question or 'monthly' in question:
        result = df.groupby('Month')['Total'].sum().sort_values(ascending=False)
        data = f"Monthly Sales:\n{result.to_string()}"
    elif 'barent' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-Barent Qty'].sum().sort_values(ascending=False)
        data = f"Barent Qty by TSE:\n{result.to_string()}"
    elif 'royal' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-Royal Ace Qty'].sum().sort_values(ascending=False)
        data = f"Royal Ace by TSE:\n{result.to_string()}"
    elif 'dennis' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-Dennis Gold Qty'].sum().sort_values(ascending=False)
        data = f"Dennis Gold by TSE:\n{result.to_string()}"
    elif 'bl ga' in question or 'blga' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-BL GA Qty'].sum().sort_values(ascending=False)
        data = f"BL GA by TSE:\n{result.to_string()}"
    elif 'bl pure' in question or 'blpure' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-BL Pure Qty'].sum().sort_values(ascending=False)
        data = f"BL Pure by TSE:\n{result.to_string()}"
    elif 'cnc' in question or 'rum' in question:
        result = df.groupby('TSE/Sales Man Name')['Sale-CNC RUM Qty'].sum().sort_values(ascending=False)
        data = f"CNC RUM by TSE:\n{result.to_string()}"
    elif 'product' in question or 'item' in question or 'brand' in question:
        result = df[tse_cols].sum().sort_values(ascending=False)
        data = f"Product wise Total Sales:\n{result.to_string()}"
    elif 'total' in question or 'kul' in question:
        total = df['Total'].sum()
        data = f"Total Sales: {total}"
    elif 'excise' in question:
        result = df.groupby('Excise Code')['Total'].sum().sort_values(ascending=False).head(5)
        data = f"Top Excise Codes:\n{result.to_string()}"
    else:
        data = f"RSD Sales Data available. Puchho: Top TSE, Department, Party, Month, Product, Barent, Royal, Dennis, BL GA, BL Pure, CNC RUM, Total"
    
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        system="Tu RSD Sales AI assistant hai. Given data ko friendly aur clear format mein present kar. Emojis use kar. Short rakho.",
        messages=[{"role": "user", "content": f"Sawaal: {request.message}\nData: {data}"}]
    )
    return {"reply": response.content[0].text}