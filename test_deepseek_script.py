import os
import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

url = "https://api.deepseek.com/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}
payload = {
    "model": "deepseek-flash",
    "messages": [
        {"role": "user", "content": "Salut, confirme-moi que DeepSeek fonctionne dans le script."}
    ],
    "thinking": {"type": "disabled"},
    "stream": False
}

response = requests.post(url, headers=headers, json=payload)
if response.status_code == 200:
    print("Succès :", response.json()["choices"][0]["message"]["content"])
else:
    print(f"Erreur {response.status_code} :", response.text)
