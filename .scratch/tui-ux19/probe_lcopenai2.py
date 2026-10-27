import re
text = open(r"D:\python_env\Lib\site-packages\langchain_openai\chat_models\base.py", encoding="utf-8").read()
lines = text.splitlines()
for i, l in enumerate(lines):
    if "reasoning" in l.lower():
        print(i+1, l.strip()[:160])
EOF_MARKER=None
