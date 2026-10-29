import json
import argparse
from pathlib import Path
from .adversarial_cases import CASES
def main():
    parser=argparse.ArgumentParser(description="Write Promptfoo-compatible adversarial cases.")
    parser.add_argument("--output",type=Path,default=Path("data/adversarial_cases.jsonl"))
    args=parser.parse_args()
    p=args.output; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text("".join(json.dumps({"vars":{"user":user},"metadata":{"id":f"ADV-{i:02d}","pressure":pressure}},ensure_ascii=False)+"\n" for i,(pressure,user) in enumerate(CASES,1)),encoding="utf-8")
    print(f"Wrote {len(CASES)} cases to {p}")
if __name__=="__main__": main()
