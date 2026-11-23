"""Decode Nuxt 3 __NUXT_DATA__ (devalue) payload from a Kungal page HTML."""
import json
import re
import sys


def extract_payload(html: str):
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("no __NUXT_DATA__ found")
    return json.loads(m.group(1))


def decode(data):
    cache = {}

    def resolve(i):
        if isinstance(i, int):
            if i in cache:
                return cache[i]
            node = data[i]
            if isinstance(node, dict):
                # special descriptors
                if len(node) == 1:
                    k, v = next(iter(node.items()))
                    if k in ("Reactive", "ShallowReactive", "Ref", "ShallowRef",
                             "EmptyRef", "ShallowReactiveRef"):
                        out = resolve(v)
                        cache[i] = out
                        return out
                    if k in ("Set", "Map", "Date", "BigInt", "RegExp", "URL",
                             "Object", "Null", "Undefined", "NaN", "Infinity",
                             "-Infinity", "-0"):
                        if k == "Set":
                            out = [resolve(x) for x in v]
                        elif k == "Map":
                            out = {str(resolve(v[j])): resolve(v[j + 1])
                                   for j in range(0, len(v), 2)}
                        elif k == "Object":
                            out = {}
                        elif k == "Null":
                            out = None
                        elif k == "Undefined":
                            out = None
                        elif k == "Date":
                            out = v
                        elif k == "URL":
                            out = v
                        else:
                            out = v
                        cache[i] = out
                        return out
                out = {}
                cache[i] = out
                for k, v in node.items():
                    out[k] = resolve(v)
                return out
            if isinstance(node, list):
                if node and isinstance(node[0], str) and node[0] in (
                        "Reactive", "ShallowReactive", "Ref", "ShallowRef"):
                    out = resolve(node[1])
                    cache[i] = out
                    return out
                out = []
                cache[i] = out
                for v in node:
                    out.append(resolve(v))
                return out
            cache[i] = node
            return node
        return i

    return resolve(0)


def main(path):
    html = open(path, encoding="utf-8", errors="replace").read()
    payload = extract_payload(html)
    root = decode(payload)
    data = root.get("data") if isinstance(root, dict) else None
    if data is None:
        print(json.dumps(root, ensure_ascii=False)[:2000])
        return
    keys = list(data.keys())
    print("PAYLOAD KEYS:")
    for k in keys:
        print("  -", k[:160])
    for k in keys:
        if k.startswith("api:works"):
            val = data[k]
            body = val.get("data", val) if isinstance(val, dict) else val
            items = body.get("items") if isinstance(body, dict) else None
            print("\nWORKS KEY:", k)
            print("ITEM COUNT:", len(items) if items else None)
            if items:
                print("\nFIRST ITEM:")
                print(json.dumps(items[0], ensure_ascii=False, indent=2)[:4000])
                print("\nITEM KEYS:", sorted(items[0].keys()))
                print("\nNAMES:")
                for it in items:
                    print(" ", it.get("id"), "|", it.get("name_cn") or it.get("name") or it.get("name_en"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"D:\project\Ds 1\kungal\galgame.html")
