; LCD mirror over MIDI for OS 3.16 (experiment).  Built by mods/build_lcdmirror316.py,
; hooks in mods/LCDMIRROR316.args; design, protocol and evidence:
; notes/lcd_mirror_midi.md.  Viewer: tools/lcd_mirror_midi_viewer.py.
;
; Every 100 Hz tick, inside 3.16's tick interrupt, the cave compares the screen
; with its copy of what the viewer has and sends at most one SysEx message (64
; bytes or fewer) into the bulk ring of one MIDI OUT:
;
;   text:     3.16's BIOS-copy text shadow BIOS_DS_SEG:662B (40 x 8 codes), the
;             cursor word BIOS_DS_SEG:68AB and the OS cursor-mode byte [1D02];
;   graphics: while the Mixer page shows pixels ([95C9] != 0), the framebuffer
;             DGROUP:FB (30 bytes x 64 rows), scanned LM_SCAN bytes per tick.
;
; Rules (notes/lcd_mirror_midi.md "Hook"): every register is kept; IF stays 0
; (the tick handler never sets it; the work is bounded: one row or one LM_SCAN
; slice, one message); nothing is sent while 3.16 suppresses MIDI output
; ([SO_ERR] != 0), while the transport runs ([LM_TRANSPORT] >= 6: the sequencer
; task waits for every OUT ring to drain), while a task is inside send_block,
; or unless the ring is empty.  A message enters the ring whole with interrupts
; off, and the tick never runs while a task message is half queued, so no
; message is split by another.

bits 16
cpu 186
org 0

%include "profile.inc"

; profile_316.inc defines two Do-list entries as PMONEY cave strings; this cave has
; no Do list, so the names exist only to satisfy those equates.
editdo_copy_text  equ 0
editdo_trunc_text equ 0

%ifndef LM_PORT
 %define LM_PORT 4                      ; MIDI OUT 1-4 = A-D; build_lcdmirror316.py --port
%endif

LM_VERSION   equ 2                      ; mod version in HELLO
LM_PROTO     equ 2                      ; protocol version in HELLO
LM_SHADOW    equ 0x662B                 ; BIOS_DS_SEG: text shadow, row * 40 + column
LM_CURSOR    equ 0x68AB                 ; BIOS_DS_SEG: cursor 0..13Fh (word)
LM_CMODE     equ 0x1D02                 ; DGROUP: cursor mode the OS gave INT 43 AX=2 (3.50 1D1A)
LM_MIXFLAG   equ 0x95C9                 ; DGROUP: 1 while the Mixer page shows pixels (3.50 98DC)
LM_TRANSPORT equ 0xA49B                 ; DGROUP: transport state, 0 stopped, >= 6 running (3.50 A7AE)
LM_BULKON    equ 0x965C                 ; DGROUP: bulk ring active, bit per OUT (TxRdy ISR 2C08)
LM_FB_SIZE   equ 30 * 64
LM_SCAN      equ 128                    ; framebuffer bytes compared per tick (15 ticks a frame)
RUN          equ 0x7D                   ; ROW run token: 7D n c (protocol 2)
RUN_MIN      equ 4
LM_ROW       equ 30                     ; framebuffer bytes per row (PCOPY distance)
LM_PIX       equ 32                     ; framebuffer bytes per PIX message
LM_CAP       equ 0x5FA                  ; bulk ring capacity (3.16 MIDI init)
LM_BUDGET    equ 64                     ; ring bytes allowed after a push (the Play bound)
LM_PER_TICK  equ 3                      ; messages built per tick at most
LM_START     equ 200                    ; ticks after the hook first runs before anything is sent
LM_IDLE      equ 500                    ; ticks without a message before a HELLO
LM_REFRESH   equ 1500                   ; HELLO + full repaint at least this often (15 s)
LM_HOLD      equ 40                     ; ticks of silence after 3.16 sends on the mirror's port
LM_MAXMSG    equ 64

%if LM_PORT == 1
LM_RING      equ 0x132E
%elif LM_PORT == 2
LM_RING      equ 0x1930
%elif LM_PORT == 3
LM_RING      equ 0x1F32
%elif LM_PORT == 4
LM_RING      equ 0x2534
%else
 %error LM_PORT must be 1-4
%endif
AMX_SEG      equ 0x47BF                 ; 3.16's AMX kernel (Vailixi FB00)
AMX_NEST_PTR equ 0x003C                 ; AMX_SEG: far pointer to the kernel data
AMX_NEST     equ 0x10                   ; byte there: interrupt nesting (47BF:016B)
LM_TXSH      equ SO_TXSH + LM_PORT - 1  ; TE7774 control shadow of the port
LM_TXPORT    equ 0xC6 + 8 * (LM_PORT - 1)

; ---------------------------------------------------------------- the tick

; CALLF from the tick handler 2B50:005C (LCDMIRROR316.args), replacing its
; CALLF 47BF:018E, the AMX interrupt exit.  Here the handler has saved every
; register (AMX entry 47BF:0151), sent its end of interrupt (OUT C010h,60h) and
; runs on the AMX interrupt stack with IF = 0; the exit expects this CALLF's
; return address on top of the stack, so the cave leaves the stack as it found it
; and jumps there.  Registers are kept anyway.
lm_tick:
        pusha
        push ds
        push es
        cld
        mov ax, AMX_SEG                 ; the AMX nesting byte: 0 at the outermost
        RELOC_PREV                      ; interrupt (its entry 47BF:0166 decrements it
        mov es, ax                      ; and switches stacks only from 0)
        les bx, [es:AMX_NEST_PTR]
        cmp byte [es:bx+AMX_NEST], 0
        jne .nested                     ; inside another ISR, whose mask still holds: no work
        call lm_work
.nested:
        pop es
        pop ds
        popa
        FJMP T_FB00_0194                ; AMX interrupt exit, returns to 2B50:0061 (IRET)

; JMPF from send_block 3286:0039 (Vailixi DC5B:003B), replacing its first eight
; bytes PUSH BP / MOV BP,SP / CMP BYTE [9331],0.  The stock body, with a count
; of task messages being queued around it: the tick sends nothing while it is
; non-zero (task 2 can nest inside task 7's call, hence a count).  Arguments as
; stock (caller's CALLF frame): buffer far [bp+6], count [bp+10], port byte
; [bp+12] 1-4.  A port outside 1-4, which stock would look up past its ring
; table, queues nothing.  Clobbers AX, BX, CX, flags (stock: the same).
lm_send_block:
        push bp
        mov bp, sp
        cmp byte [SO_ERR], 0
        jne .ret
        mov bl, [bp+12]
        cmp bl, LM_PORT                 ; 3.16 uses the mirror's port: the mirror waits
        jne .other                      ; LM_HOLD ticks, so live notes do not queue behind it
        mov word [cs:lm_hold], LM_HOLD
.other: dec bl
        js .ret
        cmp bl, 3
        ja .ret
        sub bh, bh
        shl bx, 1
        mov bx, [cs:bx+lm_rings]
        inc byte [cs:lm_inflight]
        push ds
        push si
        lds si, [bp+6]
.b:     mov cl, [si]
        inc si
        FCALL T_DA09_0030               ; one byte into RING_SEG:BX, PUSHF/CLI inside
        dec word [bp+10]
        jnz .b
        pop si
        pop ds
        dec byte [cs:lm_inflight]
.ret:   pop bp
        retf

lm_rings: dw 0x132E, 0x1930, 0x1F32, 0x2534    ; = 3286:0000 (checked by the builder)

; ---------------------------------------------------------------- one tick's work

; Gates first, with IF = 0 (as entered).  Then, with interrupts enabled (still
; inside the AMX bracket: a nested interrupt counts up AMX's nesting level and its
; exit returns here without a task switch; no task can run, so the shadow and FB
; cannot change under the scan), up to LM_PER_TICK messages are built and queued.
; A built message waits in lm_msg (lm_pending) until the ring holds at most
; LM_BUDGET - its length bytes, so the ring never holds more than LM_BUDGET bytes
; of mirror and stock together on entry to a push: at Play the sequencer waits
; for at most LM_BUDGET bytes (20.5 ms at 31,250 baud), as with an empty-ring rule,
; but the wire stays busy.  Returns with IF = 0.
lm_work:
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        cmp byte [cs:lm_up], 0
        jne .up
        inc word [cs:lm_wait]
        cmp word [cs:lm_wait], LM_START
        jb .ret
        call lm_ring_count              ; CF = 1: the ring is not set up yet
        jc .ret
        mov byte [cs:lm_up], 1
        mov byte [cs:lm_want], WANT_HELLO | WANT_FULL
.up:    cmp byte [SO_ERR], 0            ; 3.16 has MIDI output suppressed
        je .ok
        mov byte [cs:lm_err], 1         ; its error box may flush the rings
.ret:   ret
.ok:    cmp byte [cs:lm_err], 0
        je .err0
        mov byte [cs:lm_err], 0
        or byte [cs:lm_want], WANT_FULL
.err0:  inc word [cs:lm_since]
        cmp word [cs:lm_since], LM_REFRESH
        jb .fresh
        or byte [cs:lm_want], WANT_HELLO | WANT_FULL    ; repairs any cut message, shows late viewers
.fresh: cmp byte [LM_TRANSPORT], 0      ; count-in, wait for key, playing, recording:
        je .stopped                     ; only keep the transmitter going
        cmp byte [cs:lm_playing], 0
        jne .kick
        mov byte [cs:lm_playing], 1     ; Play: a message still draining may be cut by
        call lm_ring_count              ; MTC (F1) on this port, so repaint after Stop
        jc .kick
        or ax, ax
        jz .kick
        mov byte [cs:lm_cutrisk], 1
        jmp .kick
.stopped:
        cmp byte [cs:lm_playing], 0
        je .still
        mov byte [cs:lm_playing], 0
        cmp byte [cs:lm_cutrisk], 0
        je .still
        mov byte [cs:lm_cutrisk], 0
        or byte [cs:lm_want], WANT_FULL
.still: cmp word [cs:lm_hold], 0
        je .free
        dec word [cs:lm_hold]
        jmp .kick
.free:
        cmp byte [cs:lm_inflight], 0    ; a task message is half queued
        jne .kick
        mov byte [cs:lm_n], LM_PER_TICK
..@lm_if_on:
        sti
.loop:  cmp byte [cs:lm_pending], 0
        jne .try
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        mov ax, BIOS_DS_SEG
        RELOC_PREV
        mov es, ax
        call lm_next                    ; CF = 1: a message is built
        jnc .idle
        mov byte [cs:lm_pending], 1
        mov word [cs:lm_idle], 0
.try:   call lm_push                    ; CF = 1: it went in
        jnc .stop
        dec byte [cs:lm_n]
        jnz .loop
        jmp short .stop
.idle:  inc word [cs:lm_idle]
        cmp word [cs:lm_idle], LM_IDLE
        jb .stop
        mov word [cs:lm_idle], 0
        or byte [cs:lm_want], WANT_HELLO
.stop:
..@lm_if_off:
        cli
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
.kick:  call lm_ring_count              ; bytes waiting: keep the transmitter on (the
        jc .ret                         ; TxRdy ISR drops a port that was not ready)
        or ax, ax
        jz .ret
        jmp lm_kick

; AX = bytes in the port's bulk ring; CF = 1 if the ring does not hold its
; capacity (not created yet, or not the ring this build expects).
lm_ring_count:
        push ds
        mov ax, RING_SEG
        RELOC_PREV
        mov ds, ax
        cmp word [LM_RING], LM_CAP
        jne .no
        mov ax, [LM_RING + 2]
        pop ds
        clc
        ret
.no:    pop ds
        stc
        ret

; Queue the built message if the ring then holds at most LM_BUDGET bytes, and
; start the transmitter, with interrupts off (as 3033:003E and 3286:0086 do per
; byte).  The message was built backward (lm_begin), so its bytes lie in memory
; in the order the ring stores them: the ring's put index counts down, so the
; first byte goes at put-1, and one REP MOVSB per contiguous piece copies it (two
; when the message wraps at index 0).  CF = 1 if it went in (lm_pending cleared,
; sequence number advanced); CF = 0 leaves it pending.  Keeps the interrupt flag.
lm_push:
        pushf
        cli
        push ds
        mov ax, RING_SEG
        RELOC_PREV
        mov es, ax
        mov bx, LM_RING
        mov cx, [cs:lm_len]
        mov ax, [es:bx+2]
        add ax, cx
        cmp ax, LM_BUDGET
        ja .wait
        add [es:bx+2], cx
        mov dx, [es:bx+4]               ; put index
        mov si, [cs:lm_start]
        push cs
        pop ds
        cmp cx, dx
        jbe .one
        sub cx, dx                      ; wraps: the last CX bytes go at the top
        mov di, [es:bx]                 ; capacity (byte ring: bits 14-15 clear)
        sub di, cx
        push di                         ; the new put index
        lea di, [bx+di+8]
        rep movsb
        mov cx, dx                      ; the first `put` bytes at 0..put-1
        lea di, [bx+8]
        rep movsb
        pop dx
        jmp short .set
.one:   sub dx, cx
        mov di, dx
        lea di, [bx+di+8]
        rep movsb
.set:   mov [es:bx+4], dx
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        call lm_kick
        inc byte [cs:lm_seq]
        and byte [cs:lm_seq], 0x7F
        mov byte [cs:lm_pending], 0
        pop ds
..@lm_push_end1:
        popf
        stc
        ret
.wait:  pop ds
..@lm_push_end2:
        popf
        clc
        ret

; Start the port's transmitter as the stock kick 33AF:0043 does: the bulk-active
; bit in [LM_BULKON] (the TxRdy ISR 2C08:000E reads the bulk ring only with it,
; and clears it when the ring is empty), then the transmit interrupt bit in the
; control shadow, written to the TE7774.  DS = DGROUP, IF = 0.  Clobbers AL.
lm_kick:
        or byte [LM_BULKON], 1 << (LM_PORT - 1)
        or byte [LM_TXSH], 2
        mov al, [LM_TXSH]
        out LM_TXPORT, al
        ret

; ---------------------------------------------------------------- choosing the message

WANT_HELLO   equ 1                      ; send HELLO
WANT_FULL    equ 2                      ; send FULL, then everything
WANT_MODE    equ 4                      ; send MODE even if unchanged
WANT_CURSOR  equ 8                      ; send CURSOR even if unchanged

; In: DS = DGROUP, ES = BIOS data.  CF = 1 with a message built (lm_start,
; lm_len), or CF = 0 when nothing is due.  Segment registers change.
lm_next:
        test byte [cs:lm_want], WANT_HELLO
        jz .no_hello
        and byte [cs:lm_want], ~WANT_HELLO
        mov al, 1                       ; HELLO
        call lm_begin
        mov al, LM_PROTO
        stosb
        mov al, LM_VERSION
        stosb
        mov al, 3                       ; OS 3.16
        stosb
        mov al, 16
        stosb
        jmp lm_end
.no_hello:
        test byte [cs:lm_want], WANT_FULL
        jz .no_full
        and byte [cs:lm_want], ~WANT_FULL
        or byte [cs:lm_want], WANT_MODE | WANT_CURSOR
        mov word [cs:lm_since], 0
        mov byte [cs:lm_rows], 0xFF     ; every row whole
        mov byte [cs:lm_dcol], 0
        mov word [cs:lm_pfull], 0       ; every framebuffer byte
        mov al, 6                       ; FULL
        call lm_begin
        jmp lm_end
.no_full:
        xor ah, ah                      ; AH = 1 while the Mixer shows pixels
        cmp byte [LM_MIXFLAG], 0
        je .m
        inc ah
.m:     test byte [cs:lm_want], WANT_MODE
        jnz .mode
        cmp ah, [cs:lm_mode]
        je .same
.mode:  and byte [cs:lm_want], ~WANT_MODE
        mov [cs:lm_mode], ah
        or ah, ah
        jnz .to_pix
        mov byte [cs:lm_rows], 0xFF     ; back to text: the viewer repaints every row
        mov byte [cs:lm_dcol], 0
        or byte [cs:lm_want], WANT_CURSOR
        jmp short .send_mode
.to_pix:
        mov word [cs:lm_pfull], 0       ; into the Mixer: every framebuffer byte
.send_mode:
        mov al, 4                       ; MODE
        call lm_begin
        mov al, ah
        stosb
        jmp lm_end
.same:  or ah, ah
        jz lm_text
        jmp lm_pixels

; ---------------------------------------------------------------- text

; A row marked in lm_rows goes whole, from lm_dcol, as many codes per message as fit.
; Otherwise up to 80 cells from lm_tpos are compared with the viewer's copy per tick
; and the first changed span goes (changes closer than 3 cells merged, at most
; as many codes as fit); the scan resumes after it, so every cell gets its turn.
; After an equal slice, the cursor.
lm_text:
        push es
        pop ds                          ; DS = BIOS data (the shadow)
        mov al, [cs:lm_rows]
        or al, al
        jz .scan
        xor dx, dx                      ; DL = the lowest marked row
.low:   shr al, 1
        jc .whole
        inc dx
        jmp short .low
.whole: mov bl, [cs:lm_dcol]
        xor bh, bh
        mov bp, 39
        jmp short .span
.scan:  mov si, [cs:lm_tpos]            ; even cell; compare up to 80 cells from it
        mov cx, 320
        sub cx, si
        cmp cx, 80
        jbe .c
        mov cx, 80
.c:     shr cx, 1                       ; in words
        lea di, [si+lm_text_copy]
        add si, LM_SHADOW
        push cs
        pop es
        repe cmpsw
        jne .found
        sub si, LM_SHADOW
        cmp si, 320
        jb .k
        xor si, si
.k:     mov [cs:lm_tpos], si
        jmp lm_cursor
.found: lea ax, [si-2-LM_SHADOW]        ; the differing word's first cell
        mov bx, ax
        mov cl, [bx+LM_SHADOW]
        cmp cl, [cs:bx+lm_text_copy]
        jne .cell
        inc ax                          ; it was the second cell
.cell:  mov cl, 40
        div cl
        mov dl, al                      ; DL = row
        mov bl, ah
        xor bh, bh                      ; BX = first changed column
        mov al, 40
        mul dl
        mov si, ax                      ; SI = row * 40
        mov bp, bx                      ; BP = last changed column
        mov di, bx
        push bx
        mov bx, si                      ; BX = row * 40 while extending
.ext:   inc di
        cmp di, 40
        jae .ext_end
        mov ax, di
        sub ax, bp
        cmp ax, 3                       ; three equal cells end the span
        ja .ext_end
        mov al, [bx+di+LM_SHADOW]
        cmp al, [cs:bx+di+lm_text_copy]
        je .ext
        mov bp, di
        jmp short .ext
.ext_end:
        pop bx
.span:  mov al, 40                      ; DL row, BX first column, BP last column
        mul dl
        mov si, ax
        add si, bx                      ; SI = first cell (row * 40 + column)
        add bp, ax
        inc bp                          ; BP = the cell after the span
        mov [cs:lm_first], si
        mov byte [cs:lm_cut], 0
        mov al, 2                       ; ROW
        call lm_begin
        mov al, dl
        stosb
        mov al, bl
        stosb
        mov [cs:lm_lenpos], di
        stosb                           ; the code count, filled in below
        ; Tokens: a run of RUN_MIN or more equal codes is 7D n c, any other code
        ; goes alone, escaped.  A token takes at most 4 bytes; one is started
        ; only while 4 bytes and the F7 still fit in LM_MAXMSG.
.tok:   cmp si, bp
        jae .count
        cmp di, lm_msg + 4
        jb .short
        mov al, [si+LM_SHADOW]
        mov bx, si
.rl:    inc bx
        cmp bx, bp
        jae .rd
        cmp [bx+LM_SHADOW], al
        je .rl
.rd:    mov cx, bx
        sub cx, si                      ; CX = run length
        cmp cx, RUN_MIN
        jb .lit
        mov ah, al
        mov al, RUN
        stosb
        mov al, cl
        stosb
        mov al, ah
        call lm_esc
.cp:    mov [cs:si+lm_text_copy], al
        inc si
        loop .cp
        jmp short .tok
.lit:   mov [cs:si+lm_text_copy], al
        inc si
        call lm_esc
        jmp short .tok
.short: mov byte [cs:lm_cut], 1         ; the rest of the span next time
.count: mov ax, si                      ; the scan goes on after what was sent
        inc ax
        and ax, ~1
        cmp ax, 320
        jb .tp
        xor ax, ax
.tp:    mov [cs:lm_tpos], ax
        mov ax, si
        sub ax, [cs:lm_first]
        mov bx, [cs:lm_lenpos]
        mov [cs:bx], al                 ; codes sent
        mov al, 1
        mov cl, dl
        shl al, cl                      ; AL = this row's bit
        test [cs:lm_rows], al
        jz lm_end                       ; a changed span: the scan finds any rest
        mov ax, si                      ; next cell, row * 40 + column
        mov cl, 40
        div cl
        mov [cs:lm_dcol], ah            ; a cut whole row resumes here
        cmp byte [cs:lm_cut], 0
        jne lm_end
        mov al, 1
        mov cl, dl
        shl al, cl
        not al
        and [cs:lm_rows], al            ; the whole row went
        mov byte [cs:lm_dcol], 0
        jmp lm_end

; STOSB code AL escaped: below 7D as itself, 80..FF as 7E (AL & 7F), 7D..7F as
; 7F AL.  Keeps AL.
lm_esc: cmp al, RUN
        jb .one
        push ax
        test al, 0x80
        jz .lit
        mov al, 0x7E
        stosb
        pop ax
        push ax
        and al, 0x7F
        stosb
        pop ax
        ret
.lit:   mov al, 0x7F
        stosb
        pop ax
.one:   stosb
        ret

; CURSOR when the cursor word or the OS cursor-mode byte changed.
lm_cursor:
        mov ax, BIOS_DS_SEG
        RELOC_PREV
        mov ds, ax
        mov ax, [LM_CURSOR]
        mov bx, DGROUP_SEG
        RELOC_PREV
        mov ds, bx
        mov bl, [LM_CMODE]
        cmp ax, 40 * 8
        jb .in
        xor ax, ax                      ; not a cell: send 0, never divide past AL
.in:    test byte [cs:lm_want], WANT_CURSOR
        jnz .send
        cmp ax, [cs:lm_cur]
        jne .send
        cmp bl, [cs:lm_cmode]
        jne .send
        clc
        ret
.send:  and byte [cs:lm_want], ~WANT_CURSOR
        mov [cs:lm_cur], ax
        mov [cs:lm_cmode], bl
        mov cl, 40
        div cl                          ; AL = row, AH = column
        mov dx, ax
        mov al, 3                       ; CURSOR
        call lm_begin
        mov al, dl
        stosb
        mov al, dh
        stosb
        mov al, bl
        and al, 0x7F
        stosb
        mov al, bl
        rol al, 1
        and al, 1
        stosb
        jmp lm_end

; ---------------------------------------------------------------- pixels

; After MODE 01 or FULL every framebuffer byte is sent in order (lm_pfull counts
; up to LM_FB_SIZE); then one LM_SCAN slice per tick (lm_pscan) is compared with
; the viewer's copy (resuming after the last run) and the first difference starts a run.  A run that repeats
; what the viewer has one row up (30 bytes back) goes as PCOPY, up to 127 bytes;
; any other as PIX, LM_PIX bytes.  DS = DGROUP.
lm_pixels:
        mov si, [cs:lm_pfull]
        cmp si, LM_FB_SIZE
        jae .scan
        mov byte [cs:lm_infull], 1
        jmp short .run
.scan:  mov byte [cs:lm_infull], 0
        mov si, [cs:lm_pscan]           ; even; compare up to LM_SCAN bytes from it
        mov cx, LM_FB_SIZE
        sub cx, si
        cmp cx, LM_SCAN
        jbe .c
        mov cx, LM_SCAN
.c:     shr cx, 1
        lea di, [si+lm_fb_copy]
        add si, FB
        push cs
        pop es
        repe cmpsw
        jne .found
        sub si, FB
        cmp si, LM_FB_SIZE
        jb .keep
        xor si, si
.keep:  mov [cs:lm_pscan], si
        clc
        ret
.found: lea si, [si-2-FB]               ; the differing word's first byte
        mov al, [si+FB]
        cmp al, [cs:si+lm_fb_copy]
        jne .run
        inc si
.run:   call lm_copylen                 ; CX = PCOPY length, 0 if under RUN_MIN
        jcxz .pix
        mov al, 7                       ; PCOPY
        call lm_begin
        call lm_offset
        mov al, cl
        stosb
        xor al, al                      ; distance 30: 00 1E
        stosb
        mov al, LM_ROW
        stosb
        push si
        push di
        push es
        push cx
        lea di, [si+lm_fb_copy]         ; the viewer's copy follows
        add si, FB
        push cs
        pop es
        rep movsb
        pop cx
        pop es
        pop di
        pop si
        jmp short .done
.pix:   mov cx, LM_FB_SIZE              ; SI = first byte; CX = run length
        sub cx, si
        cmp cx, LM_PIX
        jbe .len
        mov cx, LM_PIX
.len:   mov al, 5                       ; PIX
        call lm_begin
        call lm_offset
        mov al, cl
        stosb
        push si
.group: mov bp, di                      ; 7-in-8: high-bit byte, then up to 7 bytes
        stosb                           ; (placeholder)
        xor dl, dl
        mov bl, 1
.pb:    mov al, [si+FB]
        mov [cs:si+lm_fb_copy], al
        inc si
        test al, 0x80
        jz .lo
        or dl, bl
.lo:    and al, 0x7F
        stosb
        shl bl, 1
        dec cx
        jz .gend
        cmp bl, 0x80
        jb .pb
.gend:  mov [cs:bp], dl
        or cx, cx
        jnz .group
        mov cx, si
        pop si
        sub cx, si                      ; CX = bytes sent
.done:  mov ax, si                      ; SI first byte, CX bytes: where next
        add ax, cx
        cmp byte [cs:lm_infull], 0
        je .incr
        mov [cs:lm_pfull], ax
        jmp lm_end
.incr:  inc ax                          ; the scan goes on after the run
        and ax, ~1
        cmp ax, LM_FB_SIZE
        jb .ps
        xor ax, ax
.ps:    mov [cs:lm_pscan], ax
        jmp lm_end

; STOSB the two 7-bit halves of framebuffer offset SI.  Keeps CX, SI.
lm_offset:
        mov ax, si
        shl ax, 1
        mov al, ah                      ; offset bits 7..13
        stosb
        mov ax, si
        and al, 0x7F
        stosb
        ret

; CX = how many framebuffer bytes from SI the viewer would get right by copying
; from 30 bytes back, in order, if at least RUN_MIN, else 0.  The first 30 come
; from what the viewer has (lm_fb_copy), the rest from bytes the copy itself
; writes (FB, one row up).  At most 127 and the end of FB.  DS = DGROUP; keeps
; SI; ES, DI change.
lm_copylen:
        xor cx, cx
        cmp si, LM_ROW
        jb .ret
        mov dx, LM_FB_SIZE
        sub dx, si
        cmp dx, 127
        jbe .n
        mov dx, 127                     ; DX = the most it may be
.n:     push si
        mov cx, dx
        cmp cx, LM_ROW
        jbe .a
        mov cx, LM_ROW
.a:     mov bx, cx                      ; BX = bytes compared against the copy
        lea di, [si+lm_fb_copy-LM_ROW]
        add si, FB
        push cs
        pop es
        repe cmpsb
        jne .miss
        cmp dx, bx
        jbe .all                        ; all compared, all equal
        sub si, LM_ROW                  ; then FB against FB one row up
        mov di, si
        add si, LM_ROW
        push ds
        pop es
        mov cx, dx
        sub cx, bx
        repe cmpsb
        jne .miss
.all:   mov cx, dx
        jmp short .got
.miss:  sub si, FB + 1                  ; SI = the first differing byte
        pop cx
        push cx
        sub si, cx
        mov cx, si                      ; equal bytes before it
.got:   pop si
        cmp cx, RUN_MIN
        jae .ret
        xor cx, cx
.ret:   ret

; ---------------------------------------------------------------- message buffer

; Messages are built backward from the end of lm_msg with STOSB and DF = 1, so
; in memory they read last byte first, the order the ring stores them in.
; lm_begin: AL = type; stores F0 7D 4D 33 4B type seq; leaves ES = CS, DI = the
; next byte, DF = 1.  Every byte after it is a STOSB.  Keeps AH, BX, CX, DX, SI, BP.
lm_begin:
        push cs
        pop es
        mov di, lm_msg + LM_MAXMSG - 1
        std
        push ax
        mov al, 0xF0
        stosb
        mov al, 0x7D
        stosb
        mov al, 0x4D
        stosb
        mov al, 0x33
        stosb
        mov al, 0x4B
        stosb
        pop ax
        stosb
        mov al, [cs:lm_seq]
        stosb
        ret

; F7; lm_start, lm_len; DF = 0; CF = 1 (a message is ready).
lm_end:
        mov al, 0xF7
        stosb
        cld
        inc di
        mov [cs:lm_start], di
        mov ax, lm_msg + LM_MAXMSG
        sub ax, di
        mov [cs:lm_len], ax
        stc
        ret

; ---------------------------------------------------------------- state (cave home RAM)

align 2
lm_wait:  dw 0                          ; ticks seen before start
lm_idle:  dw 0                          ; ticks without a message
lm_start: dw 0                          ; first byte of the built message
lm_len:   dw 0
lm_cur:   dw 0xFFFF                     ; cursor word the viewer has
lm_pfull: dw LM_FB_SIZE                 ; next byte of a full framebuffer send
lm_pscan: dw 0                          ; next framebuffer byte the scan compares (even)
lm_tpos:  dw 0                          ; next cell the text scan compares (even)
lm_since: dw 0                          ; ticks since the last full repaint
lm_hold:  dw 0                          ; ticks left of the hold after a 3.16 message
lm_inflight: db 0                       ; task messages being queued (lm_send_block)
lm_pending: db 0                        ; a built message waits for room
lm_n:     db 0                          ; messages left this tick
lm_playing: db 0                        ; the transport was seen running
lm_cutrisk: db 0                        ; a message was draining when it started
lm_err:   db 0                          ; [SO_ERR] was seen non-zero
lm_up:    db 0
lm_want:  db 0
lm_seq:   db 0
lm_rows:  db 0xFF                       ; rows to send whole (bit = row)
lm_dcol:  db 0                          ; column a cut whole row resumes from
lm_cut:   db 0                          ; the span in hand did not fit one message
align 2
lm_first: dw 0                          ; first cell of the ROW being built
lm_lenpos: dw 0                         ; its code-count byte in lm_msg
lm_infull: db 0                         ; the run in hand is part of a full send
lm_mode:  db 0                          ; 0 text, 1 graphics, as the viewer has it
lm_cmode: db 0xFF                       ; cursor-mode byte the viewer has
align 2
lm_msg:   times LM_MAXMSG db 0
lm_text_copy: times 320 db 0            ; the viewer's text
lm_fb_copy:   times LM_FB_SIZE db 0     ; the viewer's framebuffer

cave_copy_end:                          ; end of everything the 3.16 entry copies
%include "entry316.inc"                 ; runs only from the staging copy
cave_end:
