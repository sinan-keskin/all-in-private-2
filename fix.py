import sys

with open('helpcenter_streamlit/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if i < 26:
        new_lines.append(line)
    elif i == 26:
        new_lines.append('def render_ui():\n')
        new_lines.append('    ' + line)
    elif 26 < i < 505:
        if line.strip() == '':
            new_lines.append(line)
        else:
            new_lines.append('    ' + line)
    elif i >= 505:
        pass

new_lines.append('\n# --- wrapper (embed uyumlu) ---\n')
new_lines.append('def run(embedded: bool = False):\n')
new_lines.append('    if not embedded:\n')
new_lines.append('        try:\n')
new_lines.append('            st.set_page_config(page_title="Zendesk Help Center Çeviri", layout="wide")\n')
new_lines.append('        except Exception:\n')
new_lines.append('            pass\n')
new_lines.append('    render_ui()\n\n')
new_lines.append('if __name__ == "__main__":\n')
new_lines.append('    run(False)\n')

with open('helpcenter_streamlit/app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
