; Stock OS 3.16 bug fixes (PMONEY).  Included by wave.asm inside %ifdef PROFILE_316.
; Evidence and MAME reproductions: scratchpad polish/stock_bugs/report.md.
; Addresses are 3.16 relative seg:off (image offset = seg*16+off).
;
; F2  PGM / APS load error code (1396:0465, 1396:084F)
; F4  sound save: exact cluster check before any write (3 CALLF 3F26:0008 sites)
; F5  name lookup failure stored as a sound index (113A:10DA SET/ST1, 1396:08A7 APS)
; F1 and F3 are in-place byte patches in WAVE316.args (no cave code).

; ------------------------------------------------------------------ F2
; CALLF from 1396:0465 (image 0x13DC5) replacing  mov ax,si / neg ax / push ax /
; CALLF 063B:000B / add sp,2.  SI = worker (1396:08E1) result, < 0 here.
; CALLF from 1396:084F (image 0x141AF) replacing  push di / CALLF / add sp,2 (APS).
; Stock 3.16 negates every PGM result (blank box for -20h..-24h and disk codes)
; and no APS result (sequence-memory text for the sound errors -1..-3).
; Here only the sound errors -1..-3 become +1..+3 (category 2, the sound texts).
; Returns to the stock  xor ax,ax / pop di / pop si / leave / retf.
; Keeps SI, DI, BP, DS (063B:000B preserves SI/DI).  AX, BX, CX, DX, ES, flags clobbered
; (the stock sequence clobbers the same).
bf_pgm_err:
        mov ax, si
        jmp short bf_err
bf_aps_err:
        mov ax, di
bf_err:
        cmp ax, -3
        jl .show
        neg ax
.show:  push ax
        FCALL T_B3C7_0007               ; error box (code)
        add sp, 2
        retf

; ------------------------------------------------------------------ F4
; CALLF replacing CALLF 3F26:0008 (save Sound (index): mute, create, write, close)
; at 1C35:10B9 (image 0x1D409, Save a Sound), 3E8F:03C6 (0x3ECB6, program + sounds)
; and 3E8F:0825 (0x3F115, all programs + sounds).  Stack on entry: ret IP, ret CS,
; index; the caller pops the index.  Stock callers compare K figures that ignore
; the 38-byte header and cluster rounding (1C35:1189 PCM-only ceil K vs 1C35:13C8
; floor of free K), so a sound within one cluster of the free space passes, the
; write runs out of room, and a truncated SND whose directory size exceeds its
; cluster chain is left with box FF02 (MAME, stock 3.16).  Here the file size
; (38 + PCM bytes) is rounded up to clusters and compared with the free-cluster
; count, using the two INT 41 AX=8 returns the stock free-K helper 1C35:13C8
; uses (0009:09F0): [bp-6] is the bytes-per-cluster divisor and [bp-2] the
; free-cluster count.  Which of the three AX=8 outputs is which was fixed by the
; 40/41-free-cluster boundary test (report F4), not by fully decoding fn8.
; If it does not fit, AX = F900 (stock "not enough room", 1C35:0FD5), nothing written.
; Otherwise, or if the slot is empty / INT 41 fails, the stock saver runs with the
; caller's frame (tail jump).  Keeps BP, SI, DI, DS.
BF_SND_HDR equ 38                       ; 01 02 + 24h-byte record (saver 3F26:0045)
bf_snd_save:
        push bp
        mov bp, sp
        sub sp, 6                       ; INT41 AX=8 outs: [bp-6]=bytes/cluster, [bp-4]=mid, [bp-2]=free clusters
        push si
        push di
        mov ax, [bp+6]
        cmp ax, 128
        jae .stock
        mov dx, 0x24
        mul dx
        mov si, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        cmp byte [es:si+SND_DIR], 0
        je .stock
        mov ax, [es:si+SND_DIR+0x1C]    ; length, frames
        mov dx, [es:si+SND_DIR+0x1E]
        shl ax, 1
        rcl dx, 1                       ; mono: 2 bytes per frame
        cmp byte [es:si+SND_DIR+0x13], 1
        jne .mono                       ; 1C35:1189 tests == 1 for stereo
        shl ax, 1
        rcl dx, 1
.mono:  add ax, BF_SND_HDR
        adc dx, 0
        mov si, ax
        mov di, dx                      ; DI:SI = file bytes
        push ss
        lea ax, [bp-6]
        push ax
        push ss
        lea ax, [bp-4]
        push ax
        push ss
        lea ax, [bp-2]
        push ax
        FCALL T_CF0C_0056               ; INT 41 AX=8 -> [a]=DX, [b]=CX, [c]=BX; AX status
        add sp, 12
        or ax, ax
        jnz .stock
        mov cx, [bp-6]
        jcxz .stock
        mov ax, si
        mov dx, di
        add ax, cx
        adc dx, 0
        sub ax, 1
        sbb dx, 0
        cmp dx, cx
        jae .full                       ; quotient would not fit 16 bits
        div cx                          ; AX = clusters the file needs
        cmp ax, [bp-2]
        ja .full
.stock: pop di
        pop si
        mov sp, bp
        pop bp
        FJMP T_E905_000C                ; stock saver, caller's frame intact
.full:  mov ax, 0xF900
        pop di
        pop si
        mov sp, bp
        pop bp
        retf

; ------------------------------------------------------------------ F5
; CALLF replacing CALLF 21E7:0D1D (find Sound by name: index, or -4) where the
; result is stored as a note record's sound index without a test:
; 113A:10DA (image 0x1247A, SET/ST1 pad assignments) and 1396:08A7 (0x14207, APS
; note remap).  Stock stores -4 as sound index FCh (MAME: SET load, note 38 = FC).
; Here a negative result becomes 00FFh, the "no sound" value the PGM path stores
; (1396:04D0).  Same arguments (name far) and return convention (AX).
bf_find_or_ff:
        push bp
        mov bp, sp
        push word [bp+8]
        push word [bp+6]
        FCALL T_D0C0_0D17               ; find Sound by name
        add sp, 4
        or ax, ax
        jns .ok
        mov ax, 0x00FF
.ok:    pop bp
        retf
; ================================================================ C1 (crash)
; Corrupt PGM/APS: a 17-byte name-directory entry with no NUL in its 17 bytes
; overflows the fixed strlen (mov cx,0FFFFh / repne scasb, the "not cx" idiom)
; that copies the name -- in the PGM/APS sound worker 1396:08E1 (dest [bp-32h],
; 50 bytes) and in the shared find-by-name 21E7:0D1D (dest [bp-12h], 18 bytes).
; Bounding CX breaks the strlen idiom (and valid names); instead guarantee a NUL
; at byte 16 of every name field before it is scanned.  Two entry hooks that run
; the displaced prologue, terminate, and jump to the body.  PROVEN (code + MAME).

; find-by-name 21E7:0D1D: terminate the query [bp+8]:[bp+6] at +16 (every caller).
bf_term_find:
        push bp
        mov bp, sp
        sub sp, 0x12                    ; displaced prologue
        push es
        push bx
        les bx, [bp+6]
        mov byte [es:bx+16], 0
        pop bx
        pop es
        FJMP T_D0C0_0D1D                ; 21E7:0D23 body (push si / push di ...)

; PGM/APS sound worker 1396:08E1: terminate all 128 name-directory slots
; [bp+0E]:[bp+0C] at +16 before the per-name copy.
bf_term_worker:
        push bp
        mov bp, sp
        sub sp, 0x32                    ; displaced prologue
        push es
        push di
        push cx
        les di, [bp+0x0C]
        mov cx, 128
.loop:  mov byte [es:di+16], 0
        add di, 17
        loop .loop
        pop cx
        pop di
        pop es
        FJMP T_C20F_08E1                ; 1396:08E7 body (push si / push di ...)

; ================================================================ C2 (geometry)
; A corrupt SND/SET/ST1 loads a sound record with invalid geometry; the SND
; loader 2E26:0000 (also used per-sound by PGM/APS) and the SET loader 113A:000E
; store the header fields unvalidated.  Clamp the record at LOAD (not at play):
; after the loader closes the file, scan all 128 slots and for each occupied slot
; drop it (zero the name byte -> treated as empty) if length=0 or stereo>1, else
; clamp end (+18h) to length (+1Ch) and start (+14h) to end.  Idempotent; cheap
; (runs once per load).  Hooked at the SND close (2E26:012A) and SET close
; (113A:036E), replacing the stock close call.  PROVEN (code).
bf_sound_scan:                          ; near; clobbers AX BX CX DX ES; keeps SI DS BP
        push si
        mov cx, 128
        xor si, si                      ; si = slot*0x24 offset
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
.slot:
        mov bx, si
        add bx, SND_DIR                 ; es:bx = record
        cmp byte [es:bx], 0
        je .next                        ; empty slot
        cmp byte [es:bx+0x13], 1        ; stereo > 1 ?
        ja .drop
        mov ax, [es:bx+0x1C]
        or ax, [es:bx+0x1E]             ; length == 0 ?
        jz .drop
        ; clamp end(+18) to length(+1C)
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        cmp [es:bx+0x1A], dx
        ja .fix_end
        jb .end_ok
        cmp [es:bx+0x18], ax
        jbe .end_ok
.fix_end:
        mov [es:bx+0x18], ax
        mov [es:bx+0x1A], dx
.end_ok:
        ; clamp start(+14) to end(+18)
        mov ax, [es:bx+0x18]
        mov dx, [es:bx+0x1A]
        cmp [es:bx+0x16], dx
        ja .fix_start
        jb .next
        cmp [es:bx+0x14], ax
        jbe .next
.fix_start:
        mov [es:bx+0x14], ax
        mov [es:bx+0x16], dx
        jmp short .next
.drop:
        mov byte [es:bx], 0             ; refuse: slot becomes empty
.next:
        add si, 0x24
        loop .slot
        pop si
        ret

; SND loader close 2E26:012A (push si / callf 200D:008C): scan, then the stock close.
bf_snd_close:
        call bf_sound_scan
        push si
        FCALL T_CEE6_0086
        FJMP T_D7FA_013E                ; 2E26:0130 (add sp,2 ...)

; SET loader success exit 113A:140F (xor ax,ax / pop di / pop si / leave / retf):
; the SET sound records exist only here (its earlier close is before they are
; built), so clamp at the success return.
bf_set_done:
        call bf_sound_scan
        call bf_note_sanitize           ; a dropped degenerate sound must not leave a dangling note
        xor ax, ax
        pop di
        pop si
        leave
        retf

; ================================================================ C3 (dangling note)
; A corrupt/truncated PGM or APS can leave the active program's note records
; pointing at sound slots that did not load (empty) or out of range.  The
; voice-start 20ED:03A4 already plays nothing for an empty slot (stock 03D7),
; so this is play-safe, but to leave clean data the loaders should write 0FFh
; ("no sound") for such notes.  Wrap the PGM loader 1396:0009 and the APS loader
; 1396:04FC at their call sites: call the stock loader, then sanitize the active
; program's 64 note records.  PROVEN (code + MAME).
bf_note_sanitize:                       ; near; DS=DGROUP; clobbers AX BX CX DX SI DI ES
        mov di, [0xE2E6]                ; active program far ptr (off)
        mov dx, [0xE2E8]                ; (seg)
        add di, 0x3E                    ; first note record's sound-index byte
        mov cx, 64
.pad:
        mov es, dx
        mov al, [es:di]
        cmp al, 0xFF
        je .next
        cmp al, 0x80                    ; index >= 128 ?
        jae .mark
        mov bl, 0x24
        mul bl                          ; AX = idx*24h (idx<128; DX untouched)
        mov si, ax
        mov bx, SND_SEG
        RELOC_PREV
        mov es, bx
        cmp byte [es:si+SND_DIR], 0      ; slot empty ?
        jne .next
.mark:
        mov es, dx
        mov byte [es:di], 0xFF
.next:
        add di, 0x18
        loop .pad
        ret

bf_pgm_load_wrap:                       ; far; replaces CALLF 1396:0009 at its 2 sites
        push bp
        mov bp, sp
        push word [bp+0x0A]
        push word [bp+0x08]
        push word [bp+0x06]
        FCALL T_C20F_0003               ; stock PGM loader 1396:0009
        add sp, 6
        push ax
        call bf_note_sanitize
        pop ax
        pop bp
        retf

bf_aps_load_wrap:                       ; far; replaces CALLF 1396:04FC at its 2 sites
        push bp
        mov bp, sp
        push word [bp+0x0A]
        push word [bp+0x08]
        push word [bp+0x06]
        FCALL T_C20F_04F6               ; stock APS loader 1396:04FC
        add sp, 6
        push ax
        call bf_note_sanitize
        pop ax
        pop bp
        retf
