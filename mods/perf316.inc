; PMONEY performance items on OS 3.16 (PROFILE_316 only).  Spec and measurements:
; notes/performance.md (PMONEY re-profile, items S3, P4, R3, B2; S6 and D1a not built, below).
; Hooks: mods/WAVE316.args (performance).  Every routine does the stock work, or
; provably none of it, with fewer cycles; tests/test_perf316_diff.py executes the
; stock and the cave bytes side by side where the routine is self-contained.

; ------------------------------------------------------------ S3: empty-ring gates
; Task 2 reads five serial/event rings on every sequencer tick whether or not a
; byte arrived (Vailixi EC05:0043 / 3.16 422F:0052).  Each gate replaces one stock
; CALLF, takes the caller's arguments unchanged (the caller pops them) and returns
; at once when the stock routine would find nothing; otherwise it far-jumps to the
; stock routine with the stack untouched.  DS = DGROUP (task 2).

; CALLF from the tick 422F:0271 (Vailixi EC05:025A), replacing CALLF 3094:0008,
; the live MIDI-in reader.  Its two ring reads (indices 6/7, rings RING_SEG:0734 and
; 0D31, size 05F5h set once by the AMX create at start-up) return 0 while the
; port's complete-message count MIDI_PENDING+port is 0: the request (063Fh) exceeds
; any count the ring can hold.  The RX ISR queues a message before it counts it.
s3_live_gate:
        cmp word [MIDI_PENDING], 0      ; bytes 965E (MIDI In A) and 965F (MIDI In B)
        jne .go
        xor ax, ax                      ; as the stock routine's last empty read
        xor bx, bx
        retf
.go:    FJMP T_DA69_000A

; CALLF from 422F:0276 (Vailixi EC05:025F), replacing CALLF 3045:000B, the panel
; pad-event reader: its read (index 5, ring RING_SEG:06AC) returns 0 on an empty ring.
s3_pad_gate:
        push es
        mov ax, RING_SEG
        RELOC_PREV
        mov es, ax
        cmp word [es:0x06AE], 0         ; ring 06AC: count
        pop es
        jne .go
        xor ax, ax
        xor dx, dx
        retf
.go:    FJMP T_DA1A_000D

; CALLF from the event drain 33AF:0017 (Vailixi DD8A:0025), replacing CALLF 2EE7:001E
; (ring read, index 8 = the note-event ring RING_SEG:2B36; arguments 8, buffer, 10).
s3_evt_read:
        push es
        mov ax, RING_SEG
        RELOC_PREV
        mov es, ax
        cmp word [es:0x2B38], 0         ; ring 2B36: count
        pop es
        jne .go
        xor ax, ax
        xor dx, dx
        retf
.go:    FJMP T_D8BC_001C

; ------------------------------------------------------------ P4: stock pad lookup
; CALLF from the MIDI note handler 307E:008B and from the field editor 02D6:0506,
; replacing CALLF 301D:003B (T_D9F2_003D: first pad slot whose note is the word
; argument, FFFF if none or below 23h).  Same contract: word on the stack (caller
; pops), AX = slot 0..63 or FFFF; keeps SI, DI, BP, DS.  The 64 far helper calls
; become one REPNE SCASB over the same table (mute_pad_of_note).
pad_lookup_far:
        push bp
        mov bp, sp
        mov ax, [bp+6]
        cmp ax, 0x23
        jl .none                        ; stock: CMP DI,23h / JNL (signed)
        cmp ax, 0x80
        jae .stock                      ; the two table extensions differ from here
        call mute_pad_of_note           ; AX = slot, or MUTE_PAD_COUNT when none
        cmp ax, MUTE_PAD_COUNT
        jb .r
.none:  mov ax, 0xFFFF
.r:     pop bp
        retf
.stock: pop bp
        FJMP T_D9F2_003D

; ------------------------------------------------------------ R3: note-on wake
; JMPF from the MIDI-input ISR 2B6D:08FD (Vailixi D547:0903), the end of a complete
; channel message (2B6D:0932 has queued it).  SI = port 0/1, BX = next parser
; state, DS = DGROUP, IF = 0, ISR stack.  Count the message for the playback task's
; reader (as the B6/B8 port) and store the state.  For a note-on with velocity > 0
; while the transport is stopped, also do what stock 3.16 does for every message
; there (2B6D:0900-0928): wake task 2 and post the transport state, so the note
; sounds now instead of at the next tick.  Other messages, and everything while
; the transport runs, wait for the tick as in Vailixi 3.50.
midi_msg_done:
        inc byte [si+MIDI_PENDING]
        cmp byte [SEQ_TASK_STATE], 0
        jne .store
        mov al, [si+MIDI_MSG]           ; status; data bytes at +2 / +4 (ports interleaved)
        and al, 0xF0
        cmp al, 0x90
        jne .store
        cmp byte [si+MIDI_MSG+4], 0     ; velocity 0 is a note-off
        je .store
        push si
        push bx
        push es
        mov dl, 2                       ; task 2
        FCALL T_FB00_04AC               ; AMX wake
        push ds
        pop es
        mov bx, SEQ_TICK_MSG
        mov al, [SEQ_TASK_STATE]
        mov [bx], al
        mov byte [bx+1], 0
        xor cx, cx
        FCALL T_FB00_03B3               ; AMX post to task 2's mailbox
        pop es
        pop bx
        pop si
.store: shl si, 1
        mov [si+MIDI_STATE], bx
        FJMP T_D547_090D                ; 2B6D:0931: RET to the parser loop

; ------------------------------------------------------------ B2: REVERSE ZONE swap
; JMPF from 0B72:1BDD (Vailixi BBA2:0005), entered by PUSH CS / CALL near from the
; REVERSE handler 0B72:19B9: far frame, [bp+6] n low, [bp+8] n high, [bp+0Ah] buffer
; index.  Stock: if n <= 1200h, reverse the first n words of SND_SEG:(index*2400h) in
; place, recomputing the bound n/2 with the 32-bit runtime divide on every pass; if
; n > 1200h (or n >= 10000h) nothing; if n < 0 the loop runs zero times.
; Keeps SI, DI, BP, DS; clobbers AX, BX, CX, DX, ES (the stock routine: the same
; set, through the runtime); leaves DF = 0.
rev_words:
        push bp
        mov bp, sp
        cmp word [bp+8], 0
        jne .ret
        mov cx, [bp+6]
        cmp cx, 0x1200
        ja .ret
        shr cx, 1                       ; pairs = n div 2
        jz .ret
        push si
        push di
        push ds
        mov al, [bp+0x0A]
        cbw
        mov dx, 0x2400
        imul dx                         ; AX = index*2400h (16-bit, as stock)
        mov di, ax
        mov si, [bp+6]
        shl si, 1
        add si, ax
        sub si, 2                       ; the n-th word
        mov ax, SND_SEG
        RELOC_PREV
        mov ds, ax
        mov es, ax
        cld
        shr cx, 1                       ; two swaps per pass; CF: an odd pair count
        jnc .two
        inc cx                          ; one more pass, entered at its second swap
        jmp short .one
.two:   mov ax, [di]
        xchg ax, [si]
        stosw
        sub si, 2
.one:   mov ax, [di]
        xchg ax, [si]
        stosw
        sub si, 2
        loop .two
        pop ds
        pop di
        pop si
.ret:   pop bp
        retf

; S6 (INT 43 AX=4 printable fast path) and D1a (inline FAT12 free-cluster scan) are
; not built: the cave home must end at or below image 0x83300, where stock 3.16's SCSI
; file-list reader 2AB2:04F7 (SUB SP,100Eh on the UI stack) wraps its stack and writes
; downward (tests/test_build_wave316.py), and these were the two lowest-ranked items
; (notes/performance.md, where their specs remain).
