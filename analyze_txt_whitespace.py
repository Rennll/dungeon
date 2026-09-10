#!/usr/bin/env python3
"""Analyze whitespace patterns in Chinese novel TXT files.

Read-only analyzer. By default it writes output.txt, output_analysis.txt and
split forensic files (output_detailed_01.txt, ...), so large reports stay easy
to inspect. It never infers or rewrites paragraphs.
"""
from __future__ import annotations
import argparse, codecs
from collections import Counter
from pathlib import Path
from typing import TextIO

U3000="\u3000"; WS=" \t\u3000"
TARGETS={("U+3000x2","ASCII_SPACE_x4"),("ASCII_SPACE_x4","NO_INDENT"),("NO_INDENT","U+3000x2"),("U+3000x2","NO_INDENT")}
BLANK_TARGETS={2,5,8}

def read_text(p:Path):
    raw=p.read_bytes(); bom=False
    if raw.startswith(codecs.BOM_UTF8): enc="utf-8-sig"; bom=True
    elif raw.startswith(codecs.BOM_UTF16_LE): enc="utf-16-le"; bom=True
    elif raw.startswith(codecs.BOM_UTF16_BE): enc="utf-16-be"; bom=True
    else:
        enc="utf-8"
        for e in ("utf-8","gb18030","big5","cp950"):
            try: raw.decode(e); enc=e; break
            except UnicodeDecodeError: pass
    try: text=raw.decode(enc)
    except UnicodeDecodeError: text=raw.decode(enc,errors="replace"); enc += " (errors=replace)"
    return text.replace("\r\n","\n").replace("\r","\n"),enc,bom,raw

def lead(s):
    i=0
    while i<len(s) and s[i] in WS:i+=1
    return s[:i]

def cat(s):
    if s=="":return "EMPTY"
    w=lead(s)
    if not w:return "NO_INDENT"
    if set(w)=={U3000}:return f"U+3000x{len(w)}"
    if set(w)=={" "}:return f"ASCII_SPACE_x{len(w)}"
    if set(w)=={"\t"}:return f"TABx{len(w)}"
    return "MIXED"

def blank(s):return s.strip(WS)==""
def kind(s):return "BLANK" if blank(s) else cat(s)

def transitions(lines):
    out=Counter(); prev=None
    for s in lines:
        k=kind(s)
        if k=="BLANK":prev=None;continue
        if prev:out[(prev,k)]+=1
        prev=k
    return out

def blank_runs(lines):
    out=[];i=0
    while i<len(lines):
        if not blank(lines[i]):i+=1;continue
        a=i
        while i<len(lines) and blank(lines[i]):i+=1
        out.append((a,i))
    return out

def blocks(lines):
    out=[];a=None;c=Counter()
    for i,s in enumerate(lines):
        if blank(s):
            if a is not None:out.append((a,i,c));a=None;c=Counter()
        else:
            if a is None:a=i
            c[kind(s)]+=1
    if a is not None:out.append((a,len(lines),c))
    return out

def events(lines,limit):
    out={k:[] for k in TARGETS};prev=None
    for i,s in enumerate(lines):
        k=kind(s)
        if k=="BLANK":prev=None;continue
        if prev:
            key=(prev,k)
            if key in out and len(out[key])<limit:out[key].append(i)
        prev=k
    return out

def blank_events(lines,limit):
    out={n:[] for n in BLANK_TARGETS}
    for a,b in blank_runs(lines):
        n=b-a
        if n in out and len(out[n])<limit:out[n].append((a,b))
    return out

def context(out:TextIO,lines,a,b,hi):
    for i in range(max(0,a),min(len(lines),b)):
        out.write(f"{('>>' if i in hi else '  ')} {i+1:6d} {kind(lines[i]):18s} {lines[i]!r}\n")

def write_detail(p,source,lines,te,be,before,after,no,total):
    with p.open("w",encoding="utf-8") as o:
        o.write("="*80+f"\nDETAILED WHITESPACE EVIDENCE: {source}\nCHUNK {no}/{total}\n"+"="*80+"\n")
        o.write("Targeted contexts only; no paragraph semantics are inferred.\n")
        for k,ids in te.items():
            o.write(f"\n[{k[0]} -> {k[1]}] cases: {len(ids)}\n")
            for j,i in enumerate(ids,1):
                o.write(f"\nCASE T{j:02d} transition at lines {i}->{i+1}\n"+"-"*80+"\n")
                context(o,lines,i-before,i+after+1,{i-1,i})
        for n,runs in be.items():
            o.write(f"\n[BLANK RUN x{n}] cases: {len(runs)}\n")
            for j,(a,b) in enumerate(runs,1):
                o.write(f"\nCASE B{j:02d} blank lines {a+1}-{b}\n"+"-"*80+"\n")
                context(o,lines,a-before,b+after,set(range(a,b)))

def summary(p,lines,enc,bom,raw):
    cats=Counter(cat(s) for s in lines if not blank(s));tr=transitions(lines);br=Counter(b-a for a,b in blank_runs(lines));bl=[s for s in lines if blank(s)]
    u=a=t=m=trail=internal=0
    for s in lines:
        w=lead(s);u+=w.count(U3000);a+=w.count(" ");t+=w.count("\t");m+=len(set(w))>1
        trail+=len(s)-len(s.rstrip(U3000));rest=s[len(w):];internal+=max(rest.count(U3000)-(len(s)-len(s.rstrip(U3000))),0)
    crlf=raw.count(b"\r\n");cr=raw.count(b"\r")-crlf;lf=raw.count(b"\n")-crlf
    return f"""================================================================================
WHITESPACE ANALYSIS: {p}
================================================================================
encoding: {enc}
BOM: {'yes' if bom else 'no'}
lines: {len(lines)}
nonblank lines: {len(lines)-len(bl)}
blank lines: {len(bl)}
CRLF: {crlf}\nLF: {lf}\nCR: {cr}

--- Leading categories ---
"""+"".join(f"  {k}: {v}\n" for k,v in cats.most_common())+"""
--- Whitespace counts ---
"""+f"  U+3000 leading: {u}\n  ASCII spaces leading: {a}\n  TAB leading: {t}\n  mixed-leading lines: {m}\n  trailing U+3000: {trail}\n  internal U+3000: {internal}\n\n--- Blank-line runs ---\n"+"".join(f"  {k}: {v}\n" for k,v in sorted(br.items()))+"\n--- Indentation transitions (blank lines skipped) ---\n"+"".join(f"  {x:18s} -> {y:18s}: {n}\n" for (x,y),n in tr.most_common())

def analysis(p,lines,te,be):
    tr=transitions(lines);bs=blocks(lines);cand=[x for x in bs if x[2]["U+3000x2"]>=3]
    s=f"""================================================================================
SEMANTIC-ORIENTED ANALYSIS: {p}
================================================================================
This report organizes evidence; it does not infer paragraphs.

1. Strong structural signal
   Blank-line runs are preserved as events. Their length and location should be
   considered separately from leading indentation.

2. Leading indentation signal
   U+3000x2 is a stable formatting regime in this source. It should not be
   automatically equated with a paragraph delimiter. NO_INDENT is heterogeneous
   and may mix body openings, metadata, navigation, or separators.

3. Within blank-delimited blocks
"""
    for k in sorted(TARGETS):s+=f"   {k[0]} -> {k[1]}: {tr[k]}\n"
    s+=f"\n4. Blocks containing >=3 U+3000x2 lines: {len(cand)}\n"
    for a,b,c in cand[:30]:s+=f"   lines {a+1}-{b}: U+3000x2={c['U+3000x2']}, NO_INDENT={c['NO_INDENT']}, ASCII_SPACE_x4={c['ASCII_SPACE_x4']}\n"
    s+="""\n5. Contract guardrails for cn-epub-maker
   - Do not treat every U+3000x2 line as a paragraph boundary.
   - Do not treat NO_INDENT as one semantic class.
   - Keep blank-line runs structurally visible.
   - Leading indentation may be paragraph/presentation evidence; inspect it in document context.
   - Keep this analyzer descriptive; paragraph semantics belong to the parser contract.

6. Detailed files
"""
    for k,v in te.items():s+=f"   {k[0]} -> {k[1]}: {len(v)} cases\n"
    for n,v in be.items():s+=f"   blank run x{n}: {len(v)} cases\n"
    return s

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files",nargs="+",type=Path);ap.add_argument("--output-dir",type=Path,default=Path("."));ap.add_argument("--output-prefix",default="output")
    ap.add_argument("--context-limit",type=int,default=20);ap.add_argument("--chunk-size",type=int,default=10);ap.add_argument("--context-before",type=int,default=5);ap.add_argument("--context-after",type=int,default=5)
    args=ap.parse_args()
    if args.context_limit<1 or args.chunk_size<1 or args.context_before<0 or args.context_after<0:ap.error("limits must be valid non-negative/positive values")
    args.output_dir.mkdir(parents=True,exist_ok=True);multi=len(args.files)>1
    for src in args.files:
        text,enc,bom,raw=read_text(src);lines=text.split("\n");base=args.output_prefix+(f"_{src.stem}" if multi and args.output_prefix=="output" else "")
        te=events(lines,args.context_limit);be=blank_events(lines,args.context_limit)
        records=[("t",k,i) for k,ids in te.items() for i in ids]+[("b",n,r) for n,rs in be.items() for r in rs]
        chunks=[records[i:i+args.chunk_size] for i in range(0,len(records),args.chunk_size)] or [[]]
        for no,chunk in enumerate(chunks,1):
            ct={k:[] for k in TARGETS};cb={n:[] for n in BLANK_TARGETS}
            for typ,k,v in chunk:(ct[k] if typ=="t" else cb[k]).append(v)
            write_detail(args.output_dir/f"{base}_detailed_{no:02d}.txt",src,lines,ct,cb,args.context_before,args.context_after,no,len(chunks))
        (args.output_dir/f"{base}.txt").write_text(summary(src,lines,enc,bom,raw),encoding="utf-8")
        (args.output_dir/f"{base}_analysis.txt").write_text(analysis(src,lines,te,be),encoding="utf-8")
        print(f"FILE: {src}\n  summary: {base}.txt\n  analysis: {base}_analysis.txt\n  detailed: {len(chunks)} file(s)")
if __name__=="__main__":main()
