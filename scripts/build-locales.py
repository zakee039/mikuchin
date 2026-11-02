"""Generate web translation bundle from the three authoritative frontend/locales files."""
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
texts={lang:json.loads((root/'frontend/locales'/f'{lang}.json').read_text(encoding='utf8')) for lang in ('zh-CN','ja-JP','en-US')}
(root/'frontend/web/i18n-data.js').write_text('window.MIKUCHIN_TRANSLATIONS = '+json.dumps(texts,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf8')
print('Locales generated:', *(f'{k}:{len(v)}' for k,v in texts.items()))
