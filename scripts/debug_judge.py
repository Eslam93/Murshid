"""Quick debug: one live judge call, to see exactly what the bench judge returns.

The judge is `BENCH_JUDGE_MODEL` (Gemini Flash by default), built through the provider registry
like the bench builds it. Writes the raw reply, token counts, the finish reason (`length` means
the output budget ran out) and the JSON parse attempt to `<MURSHID_OUT_DIR>/judge_debug.txt`.

This makes one real, billed call. Nothing in the test suite runs it.

Usage:
  uv run python scripts/debug_judge.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from murshid.bench.metrics import CORRECTNESS_JUDGE_PROMPT_AR, _extract_json  # noqa: E402
from murshid.providers.factory import build_judge  # noqa: E402
from murshid.settings import SettingsError, get_settings  # noqa: E402

try:
    settings = get_settings()
except SettingsError as e:
    print(e)
    sys.exit(2)

prov = build_judge(settings.bench_judge_model, settings)

user_block = """السؤال:
ما آخر موعد مناسب لتجديد الإقامة إذا كان تاريخ الانتهاء مسجلاً في 20 رمضان 1447هـ، وما الرسوم المتوقعة لسنة واحدة؟

الإجابة الذهبية (سجل: MSA):
ينبغي تقديم طلب التجديد قبل تاريخ 20 رمضان 1447هـ بمدة لا تقل عن ثلاثين يوماً ولا تزيد عن تسعين يوماً. والرسم المتوقع لسنة واحدة هو SAR 600.

الإجابة المتنبأ بها (سجل النظام: MSA):
يجب تقديم طلب التجديد بمدة لا تقل عن 30 يوماً ولا تزيد عن 90 يوماً قبل تاريخ الانتهاء. الرسم لسنة واحدة هو SAR 600.

التقييم بصيغة JSON فقط:"""

out: list[str] = []
out.append(f"judge: {prov.name}/{prov.model_id}, available={prov.is_available()}")
out.append("")

try:
    resp = prov.generate(
        system=CORRECTNESS_JUDGE_PROMPT_AR,
        user=user_block,
        max_tokens=4000,  # bumped from 800; Gemini Pro thinking-mode consumes budget
        timeout=60,
    )
    out.append("--- response.text (repr, full) ---")
    out.append(repr(resp.text))
    out.append("")
    out.append(
        f"tokens_in={resp.input_tokens}, tokens_out={resp.output_tokens}, "
        f"latency={resp.latency_s:.2f}s, finish={resp.finish_reason} "
        f"(vendor: {resp.raw.get('finish_reason')})"
    )
    out.append("")
    out.append("--- _extract_json attempt ---")
    try:
        payload = _extract_json(resp.text or "")
        out.append("PARSED OK:")
        out.append(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception as e:
        out.append(f"PARSE ERROR: {type(e).__name__}: {e}")
except Exception as e:
    out.append(f"GENERATE ERROR: {type(e).__name__}: {e}")

output_path = settings.murshid_out_dir / "judge_debug.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text("\n".join(out), encoding="utf-8")
print(f"wrote {output_path}")
