# ROM free-space evaluation

Follow this on a ROM that is not Vailixi 3.50. The procedure below is the one that held up on that image. The file offsets, page tables, and byte counts from Vailixi are an example of a finished classification. They are not facts about the image in front of you. Re-measure every one of them.

Code owns counts, ranges, hashes, and disassembly. Jev classifies a packet of those measurements and judges whether a stated procedure is sufficient. Jev does not scan the image. A peaked Jev score is not permission to patch.

## What you are deciding

A byte is a patch candidate only when all of the following are true:

- It is filler, measured, not assumed from a long run of one value.
- No proven static transfer targets it.
- No installed translator state selects it. On Vailixi that translator is the PGR, and “installed” means a table the code can actually write.
- It is large enough to be a bank. Spans under 16 bytes are structural edges: vector slots, alignment, or the erased bytes touching a live instruction or table.
- It is not an unowned gap. A gap is unanalyzed debt. `unresolved` is not an owner. Looking like text, or looking blank, does not establish a data object.

Keep two classes apart in the report:

| Class | Meaning for a patch |
| --- | --- |
| Translator-unselected | No installed map selects the file bytes. This is the only class treated as a patch bank on Vailixi. |
| Mapped but unused on the static scan | At least one installed map can still fetch the bytes, and no static transfer lands in them. Higher conflict risk. Do not put patch code here. |
| Structural edge | Vector image, short align, or filler touching live code. Leave it. |
| Not free | Gap, owned data, or a proven consumer. |

On Vailixi 3.50 the unselected pair was file `[0x00054, 0x20000)` and `[0x74000, 0x78000)`, 147,372 bytes, all `0xFF`. A further 67,143 bytes of `0xFF` stayed visible under at least one page table. Those visible bytes were not the patch bank. The 68-byte IVT head was all `0xFF` and was still structural. Do not copy these ranges onto another dump.

## Evidence rules

- Build the linear program image first. If the dump is an interleaved pair, the chip files are not the CPU image. Record size, interleave, and SHA-256 of the linear image and of each chip.
- Cite linear-file offsets, `CS:IP`, the physical address, and the translator mode that makes that address true.
- Tag each claim `PROVEN`, `HYPOTHESIS`, or `UNDETERMINED`.
- Unknown hardware is a named boundary. Do not invent decoder, PAL, or panel behavior. Record the missing observation and continue with what the image can prove.
- A trace is one execution. An all-paths claim needs writers, aliases, and entry domains.
- `ndisasm` and Capstone mis-decode `BRKXA` (`0F E0`) and `RETXA` (`0F F0`) on a V53. Do not accept their stream across those bytes. Re-verify the opcode bytes on any other CPU before trusting a stock disassembler.
- Do not modify the stock ROM. Write generated requests and responses outside the ROM tree, and strip credentials before saving them.

## Measurement, in order

Stop at the first step you cannot do, and name it. Do not classify bytes you have not measured.

1. **Identity.** Linear image, chip layout, hash, reset fetch address, and the mode at reset.
2. **Translator.** Every mode that changes which file byte a program address reads. On this V53 family that is `XA`.
   - `XA=0`: `phys20 = (segment << 4) + offset`, then the file through the ROM mirror. Each file byte has two 20-bit aliases.
   - `XA=1`: `phys24 = PGR[(addr20 >> 14) & 63] << 14 | (addr20 & 0x3FFF)`. The page-register I/O window used here is ports `0xFF00–0xFF7E`.
   - Find every full-table writer and every later `OUT` that can still reach that window. “The known tables do not select it” is not an all-paths fact while one `OUT DX` can install a new frame.
   - `XA` is not permanently 1 after boot if the image contains `RETXA`. Split the execution at every `BRKXA` and `RETXA`.
   - Re-verify the port window and the formula on the image you have. Treat the Vailixi formula as a hypothesis until that image’s writers match it.
3. **Filler inventory.** Every run of the erased byte at length 4 or more. Record half-open file range, length, whether every byte is the erased value, the bytes on each side, and which translator states select the range. Classify one-byte aligns separately. They are not banks.
4. **Owners.** A range is owned when a consumer, a format constraint, and a bound agree. Padding needs a purpose and a boundary. Gaps stay gaps.
5. **Static transfers into each filler window.** Instruction-aligned walk only.
   - A fake `CS = file >> 4`, `IP = file & 0xF` is valid for instruction length and for absolute far targets. It is invalid for near-target file offsets when IP wrap differs.
   - Near control flow needs the real `CS` from an established entry. A `±64KiB` cloud of possible near targets poisons the result. It is sound and too weak to use.
   - A sliding search for far-pointer-shaped dwords is noise, especially inside copied data. Do not treat those hits as consumers.
   - Count a hit from an instruction fetch or from any memory operand whose translated address is inside the window.
6. **Interrupts while the translator is off.** On this image, reset clears the interrupt flag in the emulator model, and the decoded `XA=0` streams contain no `STI`. That closes maskable IRQ for those streams only. A non-maskable interrupt in that window is a pin fact, not a software fact. Name it. If the vector image is `FF FF FF FF`, compute the fetch that follows and see whether it lands in a candidate bank. On Vailixi that landing is file `0x0FFEF`, inside the low bank.
7. **Open sites.** List every `OUT DX` / `OUTSW` / `OUTSB`, including prefixes, whose port is not proved disjoint from the page-register window. One unbounded port write blocks the all-paths unread claim. Constant ports outside the window are closed. A function that loads a page-register port into a register and returns, with no `OUT` in the function and none in its callers, is not a writer.

## Control-flow traps that produced false hits

- Start the walk at a known `CS:IP`. Decoding from the middle of an instruction turns ASCII into `OUTSW`.
- A raw count of `0xFB` or `0xFA` is not `STI` or `CLI`. Those bytes occur as displacements. Disassemble.
- String `OUT` loops increment `DX`. A single constant port at the loop head is the wrong summary. Recognize the loop and the source table.
- Indirect `JMP`, `RET`, and `IRET` have no successor until the target is bounded. Say the walk stopped. Do not invent the edge.
- An `OUT` reached with a wild index is not harmless because the intended callers use a small index. If the segment contains words inside the page-register port range, a wild index can load one. On Vailixi, `DC5B:00BA` was left open for that reason.

## What is not sufficient

These were judged insufficient for an all-executions unread claim. Jev assigned the preimage procedure probability 0.99 and confidence 0.98, and assigned “the three known tables are enough” a noul of 0.06. Use that as a warning about shortcuts, not as a number you may copy onto a new image.

- Samples of some executions.
- A direct far-call scan by itself.
- “The known page tables do not select these bytes,” by itself.
- Jev’s confidence.

The procedure that is sufficient has all of these, or it stops named and unproved:

1. Every page-register writer is closed, or the claim stays open.
2. The mapped preimage is recomputed from the tables the code can install, not from a guessed map.
3. Execution is split at every translator switch.
4. Every fetch and memory operand is translated. Indirect and return targets are bounded or the walk stops.
5. Interrupt entry during the unmapped mode is either closed from the reset model or named as a physical unknown.
6. Mapped-but-unused windows get the same preimage. Unowned gaps are unreachable or decoded before any claim about those windows.
7. An unknown board decode stays an assumption. The image cannot discharge it.

## Jev

Read the live docs before the first call. They override this file on request shape, models, and limits: [https://docs.typesafe.ai/llms.txt](https://docs.typesafe.ai/llms.txt). The calls that worked used the HTTP API below. If the docs disagree with this shape, follow the docs.

### Credentials

- Load the key from a file outside the repository into `TYPESAFE_API_KEY` for the request only. On this machine the file is `/Users/peterwadams/Documents/Jev/secret.txt`: one line, the key itself, not an assignment.
- Send it only as `Authorization: Bearer <key>`.
- Do not write it into the repo, a commit, the chat, a log, or the saved request JSON.
- Do not print the key or any prefix of it.

### Call

`POST https://api.typesafe.ai/v1/systemone`

`Content-Type: application/json`

`model` is `jev-latest`. Record the concrete model name from the response.

```json
{
  "model": "jev-latest",
  "state": {},
  "questions": {
    "region_id": {
      "type": "choice",
      "instructions": "Which reuse class fits `regions.region_id` under `policy`?",
      "criteria": {
        "translator_unselected_reassignable": "Filler, no static transfer, no installed translator state selects it, at least 16 bytes.",
        "mapped_unused_reassignable": "Filler, no static transfer, at least 16 bytes, and at least one installed translator state can still fetch it.",
        "structural_edge": "Vector slot, under 16 bytes, or only the filler touching a live instruction or table.",
        "not_free": "Unanalyzed gap, not filler, or a proven consumer breaks if the bytes change."
      }
    }
  }
}
```

State is named JSON of measurements you already computed: policy, per-region file range, length, filler check, which translator states select it, static-transfer count, and what the neighboring bytes are. Question ids are for you. The instructions must carry the full meaning and must point at the state with backticked paths.

Use `choice` when the answer is one of those four classes. Use `noul` for a yes/no that is independently useful, with `criteria.true` and `criteria.false` describing the two situations. Ask every independent question over the same state in one request. Make a second request only when the first answer tells you which evidence to fetch or how to narrow the question.

### How to read the answer

- Choice probability is the mass on that option. Confidence is how peaked the distribution is. It is not the probability that the ROM is safe to patch.
- A noul near 0.5 means yes and no are about equally likely. It is not a medium intensity.
- If confidence is low or two options split the mass, do not adopt the label. Narrow the facts and ask again. On Vailixi the IVT head flipped from a weak “reassignable” to structural once the question said it was the stored vector image. Page 61 flipped once the question separated “no page table selects the file” from “XA=0 can still decode the chip.” The first label was rejected.
- If Jev’s noul disagrees with a count you computed, the count wins. The noul is residual model doubt.
- Do not ask Jev to rank open sites and then drop all but the winner. Any one unbounded writer, or a named interrupt landing inside the bank, keeps the all-paths claim unproved. A low-confidence ranking of blockers is discarded.
- Save the request and the response with the key absent. Record input and output token counts from the response.

### The three calls to make

1. **Classify.** One `choice` per filler region, same criteria, one request. Include the gaps as their own item so Jev can return `not_free` for them instead of you silently dropping them.
2. **Re-judge the splits.** A second request for any region whose distribution was flat, or whose class depends on a distinction the first question mixed together. State the narrower rule in `state` and ask the `noul` facts separately from the class `choice`.
3. **Procedure, then closure.** Ask which procedure is sufficient, with the shortcuts and the preimage procedure as `choice` criteria, plus `noul`s for the blockers you actually have: an unbounded page-register `OUT`, undecoded gaps, and any board decode the image cannot settle. After the proof attempt, send the closed facts and the open sites and ask whether the closed facts establish the all-paths claim. Expect that answer to stay no until the open sites are closed in code.

## Report

Lead with the patch banks: file range, length, filler byte, and the translator states that do not select them. Then the visible-but-unused filler, which is not a patch bank. Then the structural edges and the gaps, with sizes, so a later edit does not absorb them.

State the open sites by `CS:IP` and file offset. Say what would have to be true for each one to read or remap the bank.

Do not publish a crash percentage. There is no execution of a patched image behind that number. Say what normal mapped execution does, and name the residual paths. Separate “stock code reads or remaps these bytes” from “the patch itself is wrong.”

Leave the vector table, the reset fetch, and any computed interrupt landing inside a candidate bank unchanged, or make that landing a return-from-interrupt on purpose and record it.
