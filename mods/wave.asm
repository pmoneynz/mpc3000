; Wave view for Program/Sounds -> 6 (Edit Sound), opened with Help.
; Evidence: notes/waveform_phase0.md, notes/waveform_engine.md.
; Pixel contract: emu/wave_ref.py (screen()).
;
; Hooks: mods/WAVE.args. This file holds the view entry (help_gate at
; B060:0422, page_key at B99A:085A); the included files hold the zone, CHOP,
; audition and mute-group hooks.
; Stock addresses, segments and far targets: mods/profile.inc.
; DS = 8010 (DGROUP) in the hooked routines and throughout.
; C convention inside: preserve SI, DI, BP, DS.
; cpu 186: the stock OS uses PUSH imm (68 iw at B000:0015).

bits 16
cpu 186
org 0

%include "profile.inc"

ROW     equ 30
COLS    equ 240
MID     equ 31                  ; zero line; rows 16..47 hold the wave
TOP     equ 16
BOT     equ 47
ZOOM0   equ 16                  ; fine window: samples per column at entry
ZOOMMAX equ 64

; ---------------------------------------------------------------- hooks

; Replaces `cmp byte [bp-1],48h / jnz 0459` in B060:035D.
help_gate:
        cmp byte [bp-1], 'H'
        jne .other
        cmp byte [MODE], 'L'
        jne .help
        cmp byte [OPTION], 6
        jne .help
        mov si, 'H'                     ; return the key like any other
        FJMP T_B060_06E2
.help:  FJMP T_B060_0428
.other: FJMP T_B060_0459

; Replaces `cmp ax,75h / jnz / jmp 0AF3 / jmp 1595` in the B99A:082E loop.
; AX = key (cbw). Page frame: [bp-1] key, [bp-2] list position,
; [bp-0BCh] sound index list, DI = -1 when there is no sound.
page_key:
        cmp ax, 0x75
        jne .h
        FJMP T_B99A_0AF3
.h:     cmp ax, 'H'
        jne .out
        mov byte [bp-1], 0
        cmp di, -1
        je .out
        mov al, [bp-2]
        cbw
        lea bx, [bp-0xBC]
        add bx, ax
        mov al, [ss:bx]
        push ax
        call view
        add sp, 2
        mov [bp-1], al
        or ah, ah
        jz .out
        call zones_reopen              ; preserve map only for immediate re-entry
.out:   FJMP T_B99A_1595

; ---------------------------------------------------------------- view

; view(index): AL = key to hand back, AH = 1 to reopen Edit Sound.
; Points: 0 soft start, 1 soft end (sound record +14/+18), 2 zone start,
; 3 zone end (8010:EDBB/EDB7). sel picks one; its pair is sel & 2.
view:
        push bp
        mov bp, sp
        push si
        push di
        mov ax, [ss:bp]
        mov [cs:page_bp], ax
        mov ax, [bp+4]
        and ax, 0x00FF
        mov [cs:sound_index], ax
        mov al, [bp+4]
        cbw
        mov dx, 0x24
        imul dx
        add ax, SND_DIR
        mov [cs:rec], ax
        mov si, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        mov ax, [es:si+0x1C]
        mov dx, [es:si+0x1E]
        mov [cs:len], ax
        mov [cs:len+2], dx
        mov ax, [es:si+0x20]
        mov dx, [es:si+0x22]
        mov [cs:wbase], ax
        mov [cs:wbase+2], dx
        mov al, [es:si+0x13]
        mov [cs:stereo], al
        xor ax, ax
        mov [cs:sel], al
        mov [cs:fine], al
        mov [cs:full_ok], al
        mov [cs:plane], al
        mov [cs:onview], al
%ifdef PROFILE_316
        mov [cs:fvalid], al             ; fine columns belong to one view() call
%endif
        mov [cs:aud_too_short], al
        mov word [cs:zoom], ZOOM0
        call zones_enter
%ifdef PROFILE_316
        call lc_enter                   ; the view owns the pads while it shows a zone map
%endif
        FCALL T_B1B1_004F               ; save stock text for numeric entry
        call refresh
        FCALL T_C4C8_0F5F               ; graphics mode + blit 8010:1591
.key:
%ifdef PROFILE_316
        call lc_poll                    ; a take: chops, end of the Source, STOP
        jc .redraw
        or al, al                       ; AL = a key it read, else 0
        jnz .keyed
%endif
        push 0
        FCALL T_BDE3_000E               ; next key after the global filter
        add sp, 2
.keyed: mov bl, al
        mov ax, [KEY_REPEAT]             ; BDE3 coalesces consecutive +/- keys
        or ax, ax
        jnz .repeat_ready
        inc ax
.repeat_ready:
        mov [cs:key_repeat], ax
        mov byte [cs:aud_too_short], 0
%ifdef PROFILE_316
        call lc_dispatch                ; pads, the take, the Lazy Chop soft keys
        cmp al, 1
        je .key
        ja .redraw
%endif
        cmp byte [cs:onview], 0
        jne .dispatch
        cmp bl, 0x0D
        je .number_empty
        cmp bl, '0'
        jb .dispatch
        cmp bl, '9'
        ja .dispatch
        jmp .number
.number_empty:
        xor bl, bl
.number:
        call stock_numeric
        or ax, ax
        jz .key
        mov bl, al
.dispatch:
        cmp bl, '+'
        je .plus
        cmp bl, '-'
        je .minus
        mov al, [cs:sel]
        cmp bl, 'y'                     ; Soft Key 2: toggle Trim / Zone
        je .pair
        cmp bl, 'x'                     ; Soft Key 1: Play / Stop
        je .play
        cmp bl, '<'                     ; Left / Right: first / second point
        je .first
        cmp bl, '>'
        je .second
        cmp bl, 'z'                     ; Soft Key 3: fine / full
        je .mode
        mov cx, [cs:zoom]
        cmp bl, '^'                     ; End -> Zone; otherwise zoom in
        je .up
        cmp bl, '!'                     ; Zone/Count -> End; otherwise zoom out
        je .down
        mov ah, 1                       ; Soft Key 4 / Help: back to Edit Sound
        mov al, 'L'
        cmp bl, 'u'
        je .exit
        cmp bl, 'H'
        je .exit
        xor ah, ah                      ; mode keys: leave, the OS switches
        mov al, bl
        mov di, modes
.m:     mov bh, [cs:di]
        or bh, bh
        jz .key                         ; anything else, including 'h': ignore
        inc di
        cmp bh, bl
        je .exit
        jmp .m
.plus:  mov cl, 1                        ; View field: + = R
        cmp byte [cs:onview], 2
        jae .zone_adjust
        cmp byte [cs:onview], 0
        jne .plane
        call step
        jmp .move
.minus: mov cl, 0                        ; View field: - = L
        cmp byte [cs:onview], 2
        jae .zone_adjust
        cmp byte [cs:onview], 0
        jne .plane
        call step
        neg ax
        adc dx, 0
        neg dx
.move:  call move
        jmp .redraw
.plane: mov [cs:plane], cl
        mov byte [cs:full_ok], 0
        jmp .redraw
.zone_adjust:
        call zones_adjust
        jmp .redraw
.pair:  xor al, 2
        jmp .pt
.play:  call audition
        cmp byte [cs:aud_too_short], 0
        jne .redraw
        jmp .key
.first: cmp byte [cs:onview], 3
        je .previous_field
        cmp byte [cs:onview], 2
        jne .left_point
        cmp byte [cs:stereo], 0
        jne .previous_field
        jmp .end_point
.left_point:
        cmp byte [cs:onview], 1
        je .end_point
        and al, 2
        jmp .pt
.previous_field:
        dec byte [cs:onview]
        jmp .redraw
.end_point:
        or al, 1
        jmp .pt
.second:                                ; Start -> End -> View -> Zone -> Count
        cmp byte [cs:onview], 0
        jne .next_field
        test al, 1
        jz .sec
        cmp byte [cs:stereo], 0
        je .zone_field
        mov byte [cs:onview], 1
        jmp .redraw
.zone_field:
        mov byte [cs:onview], 2
        jmp .redraw
.next_field:
        cmp byte [cs:onview], 3
        jae .key
        inc byte [cs:onview]
        jmp .redraw
.sec:   or al, 1
.pt:    mov byte [cs:onview], 0
        mov [cs:sel], al
        jmp .redraw
.mode:  xor byte [cs:fine], 1
        jmp .redraw
.up:    cmp byte [cs:onview], 0
        jne .zin
        test al, 1
        jnz .zone_field
        jmp .zin
.down:  cmp byte [cs:onview], 2
        jae .end_point
        jmp .zout
.zin:   cmp cx, 1
        jbe .key
        shr cx, 1
        jmp .zoom
.zout:  cmp cx, ZOOMMAX
        jae .key
        shl cx, 1
.zoom:  mov [cs:zoom], cx
.redraw:
        call refresh
%ifdef PROFILE_316
        call fast_blit                  ; T_C4C8_0F0D's LC7981 sequence, ~4.6x faster
%else
        FCALL T_C4C8_0F0D               ; blit
%endif
        jmp .key
.exit:
%ifdef PROFILE_316
        call lc_leave                   ; every exit: a take is cancelled, the pads are stock
%endif
        push ax
        FCALL T_C4C8_0409               ; clear, text mode, INT 43 AX=1
        pop ax
        pop di
        pop si
        pop bp
        ret

; Scan if the columns changed, then draw. Fine: centred on the selected point.
; Plane R (stereo) is plane B at wave + len. Full and fine keep separate
; column arrays: full stays valid (full_ok) across fine visits until view entry
; or a plane change; fine is rescanned on every redraw.
refresh:
        mov ax, [cs:wbase]
        mov dx, [cs:wbase+2]
        cmp byte [cs:plane], 0
        je .w
        add ax, [cs:len]
        adc dx, [cs:len+2]
.w:     mov [cs:wave], ax
        mov [cs:wave+2], dx
        mov word [cs:cols], tops
        cmp byte [cs:fine], 0
        je .full
        mov word [cs:cols], ftops
        mov al, [cs:sel]
        call point
        mov [cs:center], ax
        mov [cs:center+2], dx
%ifdef PROFILE_316
        call fine_columns
%else
        call scan
%endif
        jmp draw
.full:  cmp byte [cs:full_ok], 0
        jne draw
        call scan
        mov byte [cs:full_ok], 1
        jmp draw

; DX:AX = accumulated wheel step: zoom or max(1,len/240), times the
; normalized-key repeat count. Saturate at len: further motion would clamp
; to the same endpoint, and a large burst must not overflow signed move.
step:
        xor dx, dx
        mov ax, [cs:zoom]
        cmp byte [cs:fine], 0
        jne .r
        mov ax, [cs:len+2]
        mov cx, COLS
        div cx
        mov bx, ax
        mov ax, [cs:len]
        div cx
        mov dx, bx
        or bx, ax
        jnz .r
        inc ax
.r:     mov bx, dx
        mul word [cs:key_repeat]
        mov cx, ax
        push dx
        mov ax, bx
        mul word [cs:key_repeat]
        pop bx
        add ax, bx
        adc dx, 0
        jnz .limit
        mov dx, ax
        mov ax, cx
        cmp dx, [cs:len+2]
        ja .limit
        jb .done
        cmp ax, [cs:len]
        jbe .done
.limit: mov ax, [cs:len]
        mov dx, [cs:len+2]
.done:  ret

; ES:DI = address of point AL (0..3).
paddr:
        cmp al, 2
        jae .z
        mov di, SND_SEG
        RELOC_PREV
        mov es, di
        mov di, [cs:rec]
        add di, 0x14
        test al, 1
        jz .r
        add di, 4
.r:     ret
.z:     push ds
        pop es
        mov di, ZONE_ST
        test al, 1
        jz .r
        mov di, ZONE_EN
        ret

; DX:AX = point AL.
point:
        call paddr
        mov ax, [es:di]
        mov dx, [es:di+2]
        ret

; Move the selected point by DX:AX (signed). The first point of a pair stays in
; [0, second], the second in [first, len].
move:
        mov [cs:delta], ax
        mov [cs:delta+2], dx
        mov al, [cs:sel]
        test al, 1
        jnz .second
        xor ax, ax
        mov [cs:lo], ax
        mov [cs:lo+2], ax
        mov al, [cs:sel]
        inc al
        call point
        mov [cs:hi], ax
        mov [cs:hi+2], dx
        jmp .go
.second:
        dec al
        call point
        mov [cs:lo], ax
        mov [cs:lo+2], dx
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        mov [cs:hi], ax
        mov [cs:hi+2], dx
.go:    call zones_limits
        mov al, [cs:sel]
        call paddr
        mov ax, [es:di]
        mov dx, [es:di+2]
        add ax, [cs:delta]
        adc dx, [cs:delta+2]
%ifdef PROFILE_316
        call lc_refuse                  ; CHOPS: an edit out of [lo, hi] is refused
        jc .refused
%endif
        cmp dx, [cs:lo+2]               ; below lo?
        jg .notlo
        jl .setlo
        cmp ax, [cs:lo]
        jae .notlo
.setlo: mov ax, [cs:lo]
        mov dx, [cs:lo+2]
        jmp .store
.notlo: cmp dx, [cs:hi+2]               ; above hi?
        jl .store
        jg .sethi
        cmp ax, [cs:hi]
        jbe .store
.sethi: mov ax, [cs:hi]
        mov dx, [cs:hi+2]
.store: mov [es:di], ax
        mov [es:di+2], dx
        call zones_store
%ifdef PROFILE_316
        call lc_after_move              ; snap a committed CHOPS slice start (D4)
.refused:
%endif
        ret

; ---------------------------------------------------------------- scan

; DX:AX = first sample of column CX (signed). Full: CX * len / 240
; (CX <= 240, len < 2^24). Fine: center + (CX - 120) * zoom.
bound:
        cmp byte [cs:fine], 0
        je .full
        mov ax, cx
        sub ax, COLS / 2
        imul word [cs:zoom]
        add ax, [cs:center]
        adc dx, [cs:center+2]
        ret
.full:  mov ax, [cs:len+2]
        mul cx
        mov bx, ax
        mov ax, [cs:len]
        mul cx
        add dx, bx
        mov bx, ax
        mov ax, dx
        xor dx, dx
        mov cx, COLS
        div cx
        xchg ax, bx
        div cx
        mov dx, bx
        ret

; Clamp signed DX:AX to [0, len]; set out when it changes.
clampx:
        or dx, dx
        jns .pos
        xor ax, ax
        xor dx, dx
        mov byte [cs:out], 1
        ret
.pos:   cmp dx, [cs:len+2]
        jb .r
        ja .cl
        cmp ax, [cs:len]
        jbe .r
.cl:    mov ax, [cs:len]
        mov dx, [cs:len+2]
        mov byte [cs:out], 1
.r:     ret

; Read min(BUF_W, len - cur) words from wave + cur into A2AE:0000.
; 3.16: min(BUF_W, fend - cur), fend = the end of the columns being scanned
; (<= len), so a fine view reads its window, not a whole buffer.
fill:
%ifdef PROFILE_316
        mov ax, [cs:fend]
        mov dx, [cs:fend+2]
%else
        mov ax, [cs:len]
        mov dx, [cs:len+2]
%endif
        sub ax, [cs:cur]
        sbb dx, [cs:cur+2]
        jnz .full
        cmp ax, BUF_W
        jbe .n
.full:  mov ax, BUF_W
.n:     mov bx, [cs:cur]
        mov cx, [cs:cur+2]
        mov [cs:bstart], bx
        mov [cs:bstart+2], cx
        add bx, ax
        adc cx, 0
        mov [cs:bend], bx
        mov [cs:bend+2], cx
        mov bx, [cs:wave]
        mov cx, [cs:wave+2]
        add bx, [cs:cur]
        adc cx, [cs:cur+2]
        inc byte [BUSY]
        push 1                          ; read
        push 0
        push ax                         ; count
        push cx
        push bx                         ; wave word address
        push strict word SND_SEG
        RELOC_PREV
        push 0
        FCALL T_CF92_000C
        add sp, 14
        dec byte [BUSY]
        ret

; Column c covers [bound(c), max(bound(c+1), bound(c)+1)). Samples outside
; [0, len) count as 0.
scan:
%ifdef PROFILE_316
        mov word [cs:scol_lo], 0
        mov word [cs:scol_hi], COLS
scan_range:                             ; columns [scol_lo, scol_hi)
        mov cx, [cs:scol_hi]            ; fend = clamp(end of the last column)
        call bound
        cmp byte [cs:fine], 0
        jne .fe
        mov ax, [cs:len]                ; full: column 239 ends at len
        mov dx, [cs:len+2]
.fe:    call clampx
        mov [cs:fend], ax
        mov [cs:fend+2], dx
        xor ax, ax
        mov [cs:bend], ax               ; empty buffer: first sample refills
        mov [cs:bend+2], ax
        mov ax, [cs:scol_lo]
        mov [cs:col], ax
%else
        xor ax, ax
        mov [cs:bend], ax               ; empty buffer: first sample refills
        mov [cs:bend+2], ax
        mov [cs:col], ax
%endif
.col:   mov cx, [cs:col]
        call bound
        mov [cs:cur], ax
        mov [cs:cur+2], dx
        mov cx, [cs:col]
        inc cx
        call bound
        cmp dx, [cs:cur+2]
        jg .hi
        jl .one
        cmp ax, [cs:cur]
        ja .hi
.one:   mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        add ax, 1
        adc dx, 0
.hi:    mov byte [cs:out], 0
        call clampx
        mov [cs:hi], ax
        mov [cs:hi+2], dx
        mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        call clampx
        mov [cs:cur], ax
        mov [cs:cur+2], dx
        mov word [cs:vmax], -32768
        mov word [cs:vmin], 32767
        cmp byte [cs:out], 0
        je .run
        xor ax, ax
        mov [cs:vmax], ax
        mov [cs:vmin], ax
.run:   mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        cmp dx, [cs:hi+2]
        jb .in
        ja .done
        cmp ax, [cs:hi]
        jae .done
.in:    cmp dx, [cs:bend+2]
        jb .have
        ja .refill
        cmp ax, [cs:bend]
        jb .have
.refill:
        call fill
        mov ax, [cs:cur]
        mov dx, [cs:cur+2]
.have:  mov cx, [cs:hi]                 ; k = min(hi, bend) - cur (<= BUF_W)
        mov bx, [cs:hi+2]
        cmp bx, [cs:bend+2]
        jb .k
        ja .kb
        cmp cx, [cs:bend]
        jbe .k
.kb:    mov cx, [cs:bend]
.k:     sub cx, ax
        add ax, cx                      ; cur += k
        adc dx, 0
        mov [cs:cur], ax
        mov [cs:cur+2], dx
        sub ax, cx                      ; SI = (old cur - bstart) * 2
        sub ax, [cs:bstart]
        shl ax, 1
        mov si, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        mov bx, [cs:vmax]
        mov dx, [cs:vmin]
.s:     mov ax, [es:si]
        add si, 2
        cmp ax, bx
        jle .nmax
        mov bx, ax
.nmax:  cmp ax, dx
        jge .nmin
        mov dx, ax
.nmin:  loop .s
        mov [cs:vmax], bx
        mov [cs:vmin], dx
        jmp .run
.done:  mov bx, [cs:col]
        mov si, [cs:cols]
        mov cl, 11
        mov ax, [cs:vmax]
        sar ax, cl
        neg ax
        add ax, MID
        mov [cs:si+bx], al              ; top row
        mov ax, [cs:vmin]
        sar ax, cl
        neg ax
        add ax, MID
        mov [cs:si+bx+COLS], al         ; bottom row
        inc bx
        mov [cs:col], bx
%ifdef PROFILE_316
        cmp bx, [cs:scol_hi]
%else
        cmp bx, COLS
%endif
        jb .col
        ret

%ifdef PROFILE_316
; Fine columns for the current centre.  Column c covers [centre + (c-120)*zoom,
; + zoom), so after the centre moves by k*zoom (same wave, same zoom) column c is
; the old column c+k: shift the arrays and scan only the k new columns.  Anything
; else (first fine redraw of this view, plane or zoom change, a move that is not a
; whole number of columns or not under 240 of them) scans all 240.
fine_columns:
        cmp byte [cs:fvalid], 0
        je .all
        mov ax, [cs:wave]
        cmp ax, [cs:fwave]
        jne .all
        mov ax, [cs:wave+2]
        cmp ax, [cs:fwave+2]
        jne .all
        mov cx, [cs:zoom]
        cmp cx, [cs:fzoom]
        jne .all
        mov ax, [cs:center]
        mov dx, [cs:center+2]
        sub ax, [cs:fcenter]
        sbb dx, [cs:fcenter+2]          ; DX:AX = delta, signed
        mov bx, ax
        sar bx, 15
        cmp bx, dx                      ; delta must fit 16 bits signed ...
        jne .all
        mov bx, ax
        or bx, bx
        jns .m
        neg bx                          ; ... and |delta| < 240*zoom
        js .all                         ; delta = -8000h
.m:     push ax
        mov ax, COLS
        mul cx                          ; 240*zoom <= 15,360
        cmp bx, ax
        pop ax
        jae .all
        cwd
        idiv cx                         ; AX = k, DX = remainder
        or dx, dx
        jnz .all
        or ax, ax
        jz .keep
        push si
        push di
        push ds
        push es
        push cs
        pop ds
        push cs
        pop es
        mov cx, COLS
        jl .right
        sub cx, ax                      ; k > 0: columns move left, scan [240-k, 240)
        cld
        mov si, ftops
        add si, ax
        mov di, ftops
        call .move
        mov si, fbots
        add si, ax
        mov di, fbots
        call .move
        mov [cs:scol_lo], cx
        mov word [cs:scol_hi], COLS
        jmp .scan
.right: neg ax                          ; k < 0: columns move right, scan [0, -k)
        sub cx, ax
        std
        mov si, ftops + COLS - 1
        sub si, ax
        mov di, ftops + COLS - 1
        call .move
        mov si, fbots + COLS - 1
        sub si, ax
        mov di, fbots + COLS - 1
        call .move
        cld
        mov word [cs:scol_lo], 0
        mov [cs:scol_hi], ax
.scan:  pop es
        pop ds
        pop di
        pop si
        call scan_range
        jmp .keep
.all:   call scan
.keep:  mov ax, [cs:center]
        mov [cs:fcenter], ax
        mov ax, [cs:center+2]
        mov [cs:fcenter+2], ax
        mov ax, [cs:wave]
        mov [cs:fwave], ax
        mov ax, [cs:wave+2]
        mov [cs:fwave+2], ax
        mov ax, [cs:zoom]
        mov [cs:fzoom], ax
        mov byte [cs:fvalid], 1
        ret
.move:  push cx                         ; CX bytes DS:SI -> ES:DI (both CS), direction DF
        rep movsb
        pop cx
        ret
%endif

; ---------------------------------------------------------------- draw

; XOR the pixels x = BX .. BX+CX-1 on rows AX .. AX+DX-1 (AX < 64, CX and
; DX >= 1). One mask per framebuffer byte the span touches, then ROW steps
; down the rows. Keeps BX, CX, SI, BP, DS, ES; clobbers AX, DX, DI, flags.
invert:
        push bp
        push bx
        push cx
        push si
        mov bp, bx
        add bp, cx                      ; BP = end x
        mov si, dx                      ; SI = rows
        mov dl, ROW
        mul dl
        add ax, FB
        mov dx, ax                      ; DX = first row, x = 0
.byte:  mov cx, bp
        mov di, bx
        and di, 7                       ; DI = first bit in this byte
        sub bx, di                      ; BX = x of the byte's bit 7
        sub cx, bx
        cmp cx, 8
        jbe .end
        mov cx, 8                       ; CX = bits up to the end (1..8)
.end:   mov ax, 0xFF00
        shr ax, cl                      ; AL = the leftmost CX bits
        mov cx, di
        mov ah, 0xFF
        shr ah, cl                      ; AH = bits from the first on
        and al, ah
        mov di, bx
        shr di, 3
        add di, dx
        mov cx, si
.row:   xor [di], al
        add di, ROW
        loop .row
        add bx, 8
        cmp bx, bp
        jb .byte
        pop si
        pop cx
        pop bx
        pop bp
        ret

; DI = framebuffer byte, CL = bit mask of pixel (BX, AX). Keeps AX, BX, DX.
pixel:
        push ax
        push dx
        mov dl, ROW
        mul dl
        mov di, bx
        shr di, 1
        shr di, 1
        shr di, 1
        add di, ax
        add di, FB
        mov cl, bl
        and cl, 7
        mov al, 0x80
        shr al, cl
        mov cl, al
        pop dx
        pop ax
        ret

; Draw the zero-terminated string at CS:SI, glyph rows AX..AX+6, first
; cell at column BX (6-pixel cells).
text:
        mov dx, bx
        shl bx, 1
        add bx, dx
        shl bx, 1
%ifdef PROFILE_316
        call pixel                      ; DI, CL = the first cell's top-left pixel; each
%endif                                  ; glyph then advances it by its 6 columns
.ch:    mov dl, [cs:si]
        or dl, dl
        jz .end
        cmp dl, 0x20
        jb .unknown
        cmp dl, 0x7E
        jbe .glyph
.unknown:
        mov dl, '?'
.glyph:
        inc si
        push si
        sub dl, 0x20
        xor dh, dh
        mov si, dx
        shl si, 1
        shl si, 1
        add si, dx                      ; 5 column bytes per glyph
        add si, font
%ifndef PROFILE_316
        call pixel                      ; DI, CL = the glyph's top-left pixel
%endif
        mov dh, 5
.c:     mov dl, [cs:si]                 ; bit 0 = top row
        inc si
        push di
.r:     shr dl, 1
        jnc .nr
        or [di], cl
.nr:    add di, ROW
        or dl, dl
        jnz .r
        pop di
        ror cl, 1                       ; past bit 0: next byte, bit 7
        adc di, 0
        dec dh
        jnz .c
%ifdef PROFILE_316
        ror cl, 1                       ; the blank sixth column: = pixel(BX + 6, AX)
        adc di, 0
%endif
        add bx, 6
        pop si
        jmp .ch
.end:   ret

; 10-character "sss.mmm.ss" of DX:AX frames at CS:DI (the OS field units:
; frames = s*44100 + ms*441/10 + samples, B99A:2619).
fmt:
        mov cx, 44100
        div cx
        mov [cs:rem], dx
        mov cx, 3
        call digits
        mov byte [cs:di], '.'
        inc di
        mov ax, [cs:rem]
        mov cx, 10
        mul cx
        mov cx, 441
        div cx
        push ax
        mov cx, 3
        call digits
        mov byte [cs:di], '.'
        inc di
        pop ax
        mov cx, 441
        mul cx
        mov cx, 10
        div cx
        neg ax
        add ax, [cs:rem]
        mov cx, 2
        call digits
        mov byte [cs:di], 0
        ret

; CX decimal digits of AX at CS:DI, zero padded; DI advances.
digits:
        add di, cx
        push di
        mov bx, 10
.d:     xor dx, dx
        div bx
        add dl, '0'
        dec di
        mov [cs:di], dl
        loop .d
        pop di
        ret

; Point AL in sss.mmm.ss at glyph rows AX = 8, column BX.
value:
        push bx
        call point
        mov di, num
        call fmt
        pop bx
        mov ax, 8
        mov si, num
        jmp text

; Wave, pair region, centre cursor (fine), text, selected value inverted.
draw:
        push ds
        pop es
        mov di, FB
        mov cx, ROW * 64 / 2
        xor ax, ax
        rep stosw
        mov si, [cs:cols]               ; the active mode's column arrays
        xor bx, bx
%ifdef PROFILE_316
        mov dl, 0x80                    ; pixel() in line: the mask rotates with BX
.x:     mov al, [cs:si+bx]
        mov ah, ROW
        mul ah
        add ax, FB
        mov di, bx
        shr di, 3
        add di, ax
        mov cl, [cs:si+bx+COLS]
        sub cl, [cs:si+bx]
        inc cl
        xor ch, ch
.y:     or [di], dl
        add di, ROW
        loop .y
        ror dl, 1
        inc bx
        cmp bx, COLS
        jb .x
%else
.x:     mov al, [cs:si+bx]
        xor ah, ah
        call pixel
        mov al, cl
        mov cl, [cs:si+bx+COLS]
        sub cl, [cs:si+bx]
        inc cl
        xor ch, ch
.y:     or [di], al
        add di, ROW
        loop .y
        inc bx
        cmp bx, COLS
        jb .x
%endif
        mov al, [cs:sel]                ; region: columns overlapping [a, b]
        and al, 2
        push ax
        call point
        mov [cs:pa], ax
        mov [cs:pa+2], dx
        pop ax
        inc al
        call point
        mov [cs:pb], ax
        mov [cs:pb+2], dx
        xor si, si                      ; bound and the column end never
        mov di, -1                      ; decrease: the columns are one run
%ifdef PROFILE_316
        cmp byte [cs:fine], 0
        jne .rc
        mov ax, [cs:len+2]              ; full: len = 240*Q + R, so
        xor dx, dx                      ; bound(c) = c*Q + floor(c*R/240), stepped
        mov cx, COLS                    ; per column instead of MUL/DIV twice
        div cx
        mov [cs:fq+2], ax
        mov ax, [cs:len]
        div cx
        mov [cs:fq], ax
        mov [cs:fr], dx
        xor ax, ax
        mov [cs:cur], ax                ; bound(0)
        mov [cs:cur+2], ax
        xor bx, bx                      ; (c*R) mod 240
.fc:    mov ax, [cs:cur]
        mov dx, [cs:cur+2]
        cmp dx, [cs:pb+2]               ; first sample <= b ?
        jg .rv
        jl .f1
        cmp ax, [cs:pb]
        ja .rv
.f1:    add ax, [cs:fq]                 ; bound(c+1)
        adc dx, [cs:fq+2]
        add bx, [cs:fr]
        cmp bx, COLS
        jb .f2
        sub bx, COLS
        add ax, 1
        adc dx, 0
.f2:    mov [cs:cur], ax
        mov [cs:cur+2], dx
        cmp si, COLS - 1                ; the last column ends past len
        jb .f3
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        add ax, 1
        adc dx, 0
.f3:    cmp dx, [cs:pa+2]               ; end > a ?
        jl .fn
        jg .fx
        cmp ax, [cs:pa]
        jbe .fn
.fx:    cmp di, -1
        jne .fn
        mov di, si
.fn:    inc si
        cmp si, COLS
        jb .fc
        jmp .rv
%endif
.rc:    mov cx, si
        call bound
        cmp dx, [cs:pb+2]               ; first sample <= b ?
        jg .rv                          ; no: nor any later column
        jl .r1
        cmp ax, [cs:pb]
        ja .rv
.r1:    mov cx, si
        inc cx
        cmp byte [cs:fine], 0
        jne .rb
        cmp cx, COLS                    ; full: the last column ends past len
        jb .rb
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        add ax, 1
        adc dx, 0
        jmp .r2
.rb:    call bound
.r2:    cmp dx, [cs:pa+2]               ; end > a ?
        jl .rn
        jg .rx
        cmp ax, [cs:pa]
        jbe .rn
.rx:    cmp di, -1                      ; DI = first column of the run
        jne .rn
        mov di, si
.rn:    inc si
        cmp si, COLS
        jb .rc
.rv:    cmp di, -1                      ; run = [DI, SI)
        je .rz
        mov bx, di
        mov cx, si
        sub cx, di
        mov ax, TOP
        mov dx, BOT - TOP + 1
        call invert
.rz:    cmp byte [cs:fine], 0           ; fine: centre cursor at the point
        je .t
        mov bx, COLS / 2
        mov cx, 1
        mov ax, TOP
        mov dx, BOT - TOP + 1
        call invert
.t:
%ifdef PROFILE_316
        call lc_markers                 ; chop / slice-start ticks (take, CHOPS)
%endif
        mov ax, SND_SEG                 ; name: 16 characters at +00
        RELOC_PREV
        mov es, ax
        mov si, [cs:rec]
        xor bx, bx
.nm:    mov al, [es:si+bx]
        mov [cs:name+bx], al
        inc bx
        cmp bx, 16
        jb .nm
        mov byte [cs:name+16], 0
        xor ax, ax
        xor bx, bx
        mov si, s_title
        call text
        xor ax, ax
        mov bx, 9
        mov si, name
        call text
        call zones_title
        mov si, labels                  ; pair labels and value columns
        test byte [cs:sel], 2
        jz .lab
        add si, 12
.lab:   mov [cs:lab], si
        mov bx, [cs:si+4]
        mov si, [cs:si]
        mov ax, 8
        call text
        mov si, [cs:lab]
        mov bx, [cs:si+6]
        mov si, [cs:si+2]
        mov ax, 8
        call text
        mov si, [cs:lab]
        mov bx, [cs:si+8]
        mov al, [cs:sel]
        and al, 2
        call value
        mov si, [cs:lab]
        mov bx, [cs:si+10]
        mov al, [cs:sel]
        or al, 1
        call value
        mov ax, 49
        xor bx, bx
        mov si, s_len
        call text
        mov di, num
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        call fmt
        mov ax, 49
        mov bx, 7
        mov si, num
        call text
        cmp byte [cs:stereo], 0         ; stereo: "View:" L or R at column 19
        je .nv
        mov ax, 49
        mov bx, 19
        mov si, s_view
        call text
        mov si, s_l
        cmp byte [cs:plane], 0
        je .vl
        mov si, s_r
.vl:    mov ax, 49
        mov bx, 24
        call text
.nv:
%ifdef PROFILE_316
        call lc_row49                   ; "Bank A", the take's offset, or a status
%endif
        mov si, s_full
        cmp byte [cs:fine], 0
        je .keys
        mov ax, [cs:zoom]               ; fine: "Zoom:nn" at column 33
        mov di, s_zoom + 5
        mov cx, 2
        call digits
        mov ax, 49
        mov bx, 33
        mov si, s_zoom
        call text
        mov si, s_fine
.keys:
%ifdef PROFILE_316
        push si
        call lc_softkeys                ; CF = 1: the take's or the zone page's row drawn
        pop si
        jc .keys_done
%endif
        mov ax, 57
        mov bx, 21
        call text
        mov ax, 57
        mov bx, 10
        mov si, s_trim
        test byte [cs:sel], 2
        jnz .pairkey
        mov si, s_zone
.pairkey:
        call text
        mov ax, 57
        xor bx, bx
        mov si, s_play
        cmp byte [cs:aud_too_short], 0
        je .playkey
        mov si, s_short
.playkey:
        call text
        mov ax, 57
        mov bx, 34
        mov si, s_exit
        call text
.keys_done:
        cmp byte [cs:onview], 2
        jae zones_focus
        cmp byte [cs:onview], 0         ; View field selected: its cell, rows 49..55
        je .pv
        mov bx, 24 * 6
        mov cx, 6
        mov ax, 49
        mov dx, 7
        jmp invert
.pv:    mov si, [cs:lab]                ; selected value, inverted, rows 7..14
        mov bx, [cs:si+8]
        test byte [cs:sel], 1
        jz .sv
        mov bx, [cs:si+10]
.sv:    mov ax, bx
        shl bx, 1
        add bx, ax
        shl bx, 1
        mov cx, 60
        mov ax, 7
        mov dx, 8
        call invert
        ret

%include "wave_playback.inc"
%include "wave_numeric.inc"
%include "wave_zones.inc"
%include "wave_chop.inc"
%include "mute_storage.inc"
%include "mute_voice.inc"
%include "mute_ui.inc"
%ifdef PROFILE_316
 %define S1A_IDIV_RUNTIME T_F800_20FA
 %define S1A_UDIV_RUNTIME T_F800_2101
 %include "s1a_divide.inc"             ; the 17 divides of the note-on layer (WAVE316.args)
 %include "ui316.inc"                 ; text-page helpers of the PROFILE_316 modules
 %include "compress.inc"               ; Program/Sounds 9: compression (Vailixi port)
 %include "xparams316.inc"             ; Other -> Extra Settings, real-time sample editing
 %include "tc316.inc"                  ; timing correct: Vailixi's 13 note values, swing
 %include "eraseall316.inc"             ; Disk 7: erase all files (Vailixi port)
 %include "syncout316.inc"              ; MIDI clock / time code to all four outputs (Vailixi port)
 %include "scsi316.inc"                 ; SCSI multi-sector and AUTO-search reset (Vailixi port)
 %include "diskutil316.inc"              ; SCSI disk copy, zero-fill, PC-readable partitions (Vailixi port)
 %include "scsistack316.inc"             ; private stack for the SCSI partition reader (stock 3.16 overrun)
 %include "bugfix316.inc"               ; stock 3.16 bug fixes (load/save, errors, mixer)
 %include "perf316.inc"                 ; performance items (notes/performance.md)
 %include "display316.inc"              ; put-char without INT 43 round trips (notes/performance.md)
 %include "lazychop316.inc"             ; Lazy Chop: pad ownership, the take, CHOPS, Convert
 %include "thru316.inc"                 ; Input Thru: live input monitoring (Mixer/Effects 6)
%endif

; Per pair: label strings, label columns, value columns.
labels: dw s_start, s_end, 0, 20, 6, 24
        dw s_zst, s_zend, 0, 19, 8, 28

s_title: db "Edit Snd:", 0
s_start: db "Start:", 0
s_end:   db "End:", 0
s_zst:   db "Zone st:", 0
s_zend:  db "Zone end:", 0
s_len:   db "Length:", 0
s_view:  db "View:", 0
s_l:     db "L", 0
s_r:     db "R", 0
s_zoom:  db "Zoom:00", 0
s_trim:  db "<Trim>", 0
s_zone:  db "<Zone>", 0
%ifdef PROFILE_316
s_play   equ cmp_s_keys + 10        ; "<Ply/Stp>", the tail of compress.inc's soft keys
%else
s_play:  db "<Ply/Stp>", 0
%endif
s_short: db "Too short", 0
s_fine:  db "<Full>", 0             ; in fine mode the key goes back to full
s_full:  db "<Fine>", 0
s_exit:  db "<Exit>", 0
modes:   db "LMFJGUSlsOK", 0            ; mode keys (D547:0006 codes)

%include "wave_font.inc"

%ifdef PROFILE_316
; T_C4C8_0F0D (1650:0F01) in the cave: LC7981 instructions 0Ah = 0 and 0Bh = 0, then
; for each of the 1,920 framebuffer bytes from FB: wait until port E2h bit 7 is
; clear, instruction 0Ch to E2h, the byte bit-reversed to E0h, the same command and
; data stream as the stock blit.  A table replaces the stock 8-step bit loop; the gap
; between the two writes is at least the stock blit's.  DS = DGROUP.  Keeps SI, DI,
; BP, DS, ES, CX; clobbers AX, BX, flags (stock: AX, BX, DX).
fast_blit:
        push si
        push cx
        mov ax, 0x0A00                  ; AH = instruction, AL = data
        call .put
        mov ax, 0x0B00
        call .put
        mov si, FB
        mov bx, bitrev
        mov cx, ROW * 64
.b:     lodsb
        cs xlatb
        mov ah, al                      ; AH = data
.w:     in al, 0xE2
        test al, 0x80
        jnz .w
        mov al, 0x0C
        out 0xE2, al
        mov al, ah
        nop
        nop
        out 0xE0, al
        loop .b
        pop cx
        pop si
        ret
.put:   push ax
.p:     in al, 0xE2
        test al, 0x80
        jnz .p
        pop ax
        xchg al, ah
        out 0xE2, al                    ; instruction
        mov al, ah
        nop
        nop
        out 0xE0, al                    ; data
        ret
bitrev:
%assign i 0
%rep 256
        db ((i & 1) << 7) | ((i & 2) << 5) | ((i & 4) << 3) | ((i & 8) << 1) | ((i & 16) >> 1) | ((i & 32) >> 3) | ((i & 64) >> 5) | ((i & 128) >> 7)
%assign i i+1
%endrep
%endif

align 2
rec:    dw 0
page_bp: dw 0
col:    dw 0
zoom:   dw 0
key_repeat: dw 1
rem:    dw 0
lab:    dw 0
cols:   dw tops                         ; tops (full) or ftops (fine)
sel:    db 0
fine:   db 0
full_ok: db 0
stereo: db 0
plane:  db 0
onview: db 0
out:    db 0
align 2
len:    dd 0
wave:   dd 0
wbase:  dd 0
cur:    dd 0
hi:     dd 0
lo:     dd 0
delta:  dd 0
center: dd 0
pa:     dd 0
pb:     dd 0
bstart: dd 0
bend:   dd 0
vmax:   dw 0
vmin:   dw 0
%ifdef PROFILE_316
fend:   dd 0                            ; end of the columns being scanned (fill)
fcenter: dd 0                           ; fine columns: centre, wave and zoom they hold
fwave:  dd 0
fq:     dd 0                            ; full-mode bounds: len div 240
fzoom:  dw 0
scol_lo: dw 0                           ; scan_range columns
scol_hi: dw COLS
fr:     dw 0                            ; len mod 240
fvalid: db 0
%endif
%ifdef PROFILE_316                     ; in the session pool (mute_storage.inc)
tops    equ cave_pool
bots    equ tops + COLS
ftops   equ tops + 2 * COLS
fbots   equ tops + 3 * COLS
name    equ tops + 4 * COLS
num     equ name + 17
%else
tops:   times COLS db 0             ; full view; bots = tops + COLS
bots:   times COLS db 0
ftops:  times COLS db 0             ; fine view; fbots = ftops + COLS
fbots:  times COLS db 0
name:   times 17 db 0
num:    times 11 db 0
%endif

%ifdef PROFILE_316
%include "banner316.inc"
%include "sysinfo316.inc"
%include "namewheel316.inc"              ; spell names with the data wheel (Extra Settings 2)
%include "trackmute316.inc"              ; SONG on the Song page: mute tracks with the pads
cave_copy_end:                          ; end of everything the 3.16 entry copies
%include "entry316.inc"                 ; runs only from the staging copy
%endif
cave_end:
