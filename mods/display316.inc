; PMONEY display speed-up on OS 3.16 (PROFILE_316 only).  Owner-approved after the
; hostile review of the display proposal (2026-10-17); proof: tests/test_display316_diff.py
; (instruction-level differential against the stock bytes with an LC7981 model) and
; notes/performance.md "Display: put-char".
;
; Step 1 (WAVE316.args, 0 cave bytes): INT 43 AX=4's control-character table walk at
; 0009:174E-1768 (img 0x17DE) becomes five compare-and-jumps to the same handlers
; (0Dh 177A, 0Ah 1787, 08h 179A, 7Fh 17A6, 0Ch 17C4, otherwise 17C8).  Exact for every
; BL: the handlers are entered with one return address fewer on the stack and SI not
; advanced; both are restored by the INT 43 epilogue, and no handler reads them.
;
; Step 2: put-char 0427:0040 (Vailixi B1B1:0036, img 0x42B0-0x42C8), printf's per-
; character output.  Stock: INT 43 AX=4 (BL = char), AX=7 (read the cursor), AX=3
; (set it to the same place: LC7981 address := [68AB], [68AF] := FFh).  Here, for a
; character other than 00h-1Fh and 7Fh, the same work without the three software
; interrupts, and the AX=7/AX=3 re-sync only where it changes the controller:
;
;   invariant I: on entry, [68AF] = FFh implies LC7981 address = [68AB].
;
; Under I the address already equals [68AB] whenever [68AF] = FFh after the put (the
; data write auto-increments it with [68AB]); the re-sync is then two redundant LCD
; instructions.  When [68AF] = 0 (unchanged character) it is still sent.  I is broken
; only by LC7981 writers outside the BIOS (1650:0F8D, 03B0:000A from segment 1650, the
; cave's fast_blit), all in graphics mode, and every way back to text runs INT 43 AX=1
; (1650:03FD), whose 183F re-establishes I (tests/test_display316_diff.py, static part;
; emu/lua/display_watch316.lua checks it at every put-char in MAME).
;
; Same contract as stock: char at [bp+6] (caller pops), returns AX = 0B00h | high byte
; of [68AB], BX = row << 8 | column; keeps CX DX SI DI BP DS ES and the entry flags;
; the BIOS body runs with IF = 1 as stock's (STI at 0009:16A6).  The LCD busy poll and
; the six NOPs after each OUT are copied from 0009:1856 (LC7981 timing, hardware H5).
; Characters 00h-1Fh and 7Fh go to the stock body at 0427:0046 unchanged.
;
; Step 3 (P only): the string writer 0427:0065 (Vailixi B1B1:005B), which most page
; text goes through, gets the same treatment: 17C8 inline per printable byte, INT 43
; AX=4 for 00h-1Fh / 7Fh, the closing AX=7 / AX=3 re-sync only when [68AF] = 0.
;
; %define DISPLAY_COMPACT (or build_wave316 --define DISPLAY_COMPACT) assembles the
; review's smaller variant MX instead: an unchanged character re-enters the stock tail
; (AX=7, AX=3) at 0427:004B; a changed one makes one INT 43 AX=4 call and skips the
; tail (after a changed put [68AF] = FFh); AX/BX synthesised as stock.

; BIOS data segment of the 3.16 BIOS copy (DS of INT 43, 0009:16B1 MOV AX,59FAh,
; relocated): text shadow, cursor and address-valid flag (notes/int43_ax4.md).
DSP_SHADOW equ 0x662B               ; 320 cells, row * 40 + column
DSP_CURSOR equ 0x68AB               ; cursor 0..13Fh (word)
DSP_VALID  equ 0x68AF               ; FFh: LC7981 address = cursor (183F), 0: stale

%ifndef DISPLAY_COMPACT
; ------------------------------------------------------------ P: full replica
; JMPF from 0427:0040 (img 0x42B0).  0009:17C8 (put), 183F (address), 1856 (LCD
; instruction + data) inline, re-sync skipped when [68AF] = FFh after the put.
fast_putc:
        push bp
        mov bp, sp
        pushf                           ; stock returns the entry flags (IRET)
        mov bl, [bp+6]
        cmp bl, 0x20
        jb .stock
        cmp bl, 0x7F
        je .stock
        sti                             ; 0009:16A6
        push ds
        mov ax, BIOS_DS_SEG
        RELOC_PREV
        mov ds, ax
        mov al, bl
        call dsp_glyph
        call dsp_tail
        pop ds
        popf
        pop bp
        retf
.stock: popf
        FJMP T_B1B1_003C                ; 0427:0046: MOV AX,4 / INT 43 ... with BL set

; JMPF from 0427:0065 (img 0x42D5, Vailixi B1B1:005B), the string writer: far
; pointer at [bp+6] (caller pops), bytes to the first 00h.  Stock: INT 43 AX=4 per
; byte, then AX=7 / AX=3 once; keeps DS and DI (pushed), returns AX and BX as
; put-char.  Here 00h-1Fh and 7Fh still go through INT 43 AX=4 (the stock path,
; class walk included); every other byte is 17C8 inline; the closing re-sync is sent
; only when [68AF] = 0.  The string is read through ES (kept), DS = BIOS data.
fast_puts:
        push bp
        mov bp, sp
        pushf
        push ds
        push di
        push es
        les di, [bp+6]
        sti
        mov ax, BIOS_DS_SEG
        RELOC_PREV
        mov ds, ax
.next:  mov bl, [es:di]
        or bl, bl
        jz .end
        inc di
        cmp bl, 0x20
        jb .bios
        cmp bl, 0x7F
        je .bios
        mov al, bl
        call dsp_glyph
        jmp short .next
.bios:  mov ax, 4                       ; control character: the stock call
        int 0x43
        jmp short .next
.end:   call dsp_tail
        pop es
        pop di
        pop ds
        popf
        pop bp
        retf

; 0009:17C8 with AL = character, DS = BIOS data: unchanged cell -> [68AF] = 0,
; otherwise store, address first if [68AF] = 0, write; cursor + 1, or re-address
; the last cell 13Fh.  Clobbers AX, BX.
dsp_glyph:
        mov bx, [DSP_CURSOR]
        cmp al, [bx+DSP_SHADOW]
        jne .changed
        mov byte [DSP_VALID], 0
        jmp short .advance
.changed:
        mov [bx+DSP_SHADOW], al
        test byte [DSP_VALID], 0xFF
        jnz .put
        push ax
        mov ax, bx
        call dsp_address
        pop ax
.put:   mov ah, 0x0C
        call dsp_lcd
.advance:
        mov ax, [DSP_CURSOR]
        cmp ax, 0x13F
        je dsp_address                  ; 17F3: the last cell re-addresses itself (its RET returns)
        inc ax
        mov [DSP_CURSOR], ax
        ret

; The stock tail AX=7 / BX=AX / AX=3: the LCD address := [68AB] (183F) unless
; [68AF] = FFh, which under I means it already is; AX = 0B00h | high byte of
; [68AB] (what 183F leaves), BX = row << 8 | column.
dsp_tail:
        test byte [DSP_VALID], 0xFF
        jnz .synced
        mov ax, [DSP_CURSOR]
        call dsp_address
.synced:
        mov ax, [DSP_CURSOR]            ; AX=7 (1835)
        mov bl, 40
        div bl
        xchg al, ah
        mov bx, ax
        mov al, byte [DSP_CURSOR+1]
        mov ah, 0x0B
        ret

; 0009:183F: [68AB] = AX, LCD address = AX, [68AF] = FFh.
dsp_address:
        mov [DSP_CURSOR], ax
        push ax
        mov ah, 0x0A
        call dsp_lcd
        pop ax
        mov al, ah
        mov ah, 0x0B
        call dsp_lcd
        mov byte [DSP_VALID], 0xFF
        ret

; 0009:1856: wait until E2h bit 7 is clear, instruction AH to E2h, data AL to E0h.
dsp_lcd:
        push ax
.busy:  in al, 0xE2
        and al, 0x80
        jnz .busy
        mov al, ah
        out 0xE2, al
        times 6 nop
        pop ax
        out 0xE0, al
        times 6 nop
        ret

%else
; ------------------------------------------------------------ MX: compact
; JMPF from 0427:0040 (img 0x42B0).  Unchanged character below the last cell:
; 17C8's unchanged arm inline, then the stock tail.  Otherwise one INT 43 AX=4
; ([68AF] = FFh and the LCD address = [68AB] afterwards) and no tail.
fast_putc:
        push bp
        mov bp, sp
        pushf                           ; stock returns the entry flags (IRET)
        mov bl, [bp+6]
        cmp bl, 0x20
        jb .stock
        cmp bl, 0x7F
        je .stock
        push ds
        mov ax, BIOS_DS_SEG
        RELOC_PREV
        mov ds, ax
        mov al, bl
        mov bx, [DSP_CURSOR]
        cmp al, [bx+DSP_SHADOW]
        jne .changed
        cmp bx, 0x13F
        jae .changed
        mov byte [DSP_VALID], 0         ; 17C8's unchanged arm, cursor below 13Fh
        inc bx
        mov [DSP_CURSOR], bx
        pop ds
        popf
        FJMP T_B1B1_0041                ; 0427:004B: AX=7, BX=AX, AX=3, POP BP, RETF
.changed:
        mov bl, al
        mov ax, 4
        int 0x43                        ; the BIOS put
        mov ax, [DSP_CURSOR]            ; AX=7: BX = row << 8 | column
        mov bl, 40
        div bl
        xchg al, ah
        mov bx, ax
        mov al, byte [DSP_CURSOR+1]     ; AX=3 leaves AX = 0B00h | high byte
        mov ah, 0x0B
        pop ds
        popf
        pop bp
        retf
.stock: popf
        FJMP T_B1B1_003C                ; 0427:0046 with BL set

; JMPF from 0427:0065 (the string writer): MX keeps the stock body.
fast_puts:
        push bp
        mov bp, sp
        push ds
        push di
        FJMP T_B1B1_0060                ; 0427:006A: LDS DI,[BP+6] and the INT 43 loop
%endif
