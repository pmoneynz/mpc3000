; OS 3.16: Name Wheel.  Spell any stock name field (sequence, track, program,
; sound, file and copy names: every type-1 field of 05C8:000D) with the data
; wheel.  PMONEY's own version of the RenameX mode of the third-party
; OS 3.39.3; its behaviour, not its code (notes/name_wheel.md).
;
; Stock 3.16's wheel offers only the field's original character and
; " -@!#$%&(){}'_" (DS 1D4E), and its first turn only opens the edit.  With
; Name Wheel ON (Extra Settings page 2, saved with the system parameters):
;   wheel / + -  step the character at the cursor through space, A-Z, 0-9 and
;                the stock symbols (read from DS 1D51), wrapping; the first
;                turn on an idle field opens the edit and steps at once
;   Up / Down    capitals / small letters, applied to the character at the
;                cursor and kept for the rest of the edit (case lock)
;   Left / Right move as stock; without a case lock the letter you land on
;                takes title case: capital at a word start, else small
; Every other key keeps its stock meaning, so the letter buttons, digits,
; PLAY (space) and PLAY START (case toggle) still type: unlike OS 3.39.3,
; nothing is swallowed.  OFF is stock 3.16 throughout.
;
; Hooks (WAVE316.args), all in the stock text-field key handler 04D5:000E
; (image 0x4D5E) and its helpers; DS = DGROUP, frame [bp+6] = key byte,
; SI and DI pushed, DI = handler result (0 = keep editing):
;   0x4DE9  nw_first       after begin_edit on an idle field's first +/- turn
;   0x4DFE  nw_edit_key    the editing-state key switch, DX = key
;   0x4FC7  nw_wheel       prologue of the stock wheel step 04D5:0277
;   0x5066  nw_reset_case  04D5:0316, the case reset at every field entry

NW_SYMS     equ 0x1D51          ; stock wheel symbols "-@!#$%&(){}'_" (13)
NW_NSYMS    equ 13
NW_SET      equ 1 + 26 + 10 + NW_NSYMS      ; 50 characters

; CF = 1 when Name Wheel applies to the active field: the setting is ON and
; the length is 1..40 (the stock buffer holds 41).  Changes AL and flags.
nw_on:  cmp byte [NW_OFF], 0
        jne .no
        mov al, [NAME_LEN]
        dec al
        cmp al, 40
        jae .no
        stc
        ret
.no:    clc
        ret

; JMP from 04D5:0099 (image 0x4DE9): an idle field took + or -, begin_edit
; has run.  DI = 0.
nw_first:
        call nw_on
        jc .turn
        mov al, [NAME_POS]              ; the replaced lines: remember the
        cbw                             ; character under the cursor
        mov bx, ax
        mov al, [bx+NAME_BUF]
        mov [NAME_ORIG], al
        FJMP T_B261_01FB
.turn:  mov ax, 1
        cmp byte [bp+6], '+'
        je .step
        neg ax
.step:  call nw_turn
        FJMP T_B261_01FB                ; return DI = 0

; FAR, in place of the stock wheel step 04D5:0277 (push cs / near call, one
; word: +1 or -1).  Keeps SI, DI, BP.
nw_wheel:
        call nw_on
        jnc .stock
        push bp
        mov bp, sp
        mov ax, [bp+6]
        call nw_turn
        pop bp
        retf
.stock: push bp                         ; the replaced prologue
        mov bp, sp
        sub sp, 6
        FJMP T_B261_0279

; JMP from 04D5:00AE (image 0x4DFE), the editing state.  DX = key.
nw_edit_key:
        call nw_on
        jnc .stock
        cmp dl, '^'
        je .capitals
        cmp dl, '!'
        je .small
        cmp dl, '<'
        je .left
        cmp dl, '>'
        je .right
.stock: mov ax, dx                      ; the replaced compare; its JZ follows
        cmp ax, 'M'
        FJMP T_B261_00AF
.capitals:
        mov byte [CASE_SMALL], 0
        jmp .lock
.small: mov byte [CASE_SMALL], 1
.lock:  mov byte [cs:nw_lock], 1
        mov bl, [NAME_POS]
        xor bh, bh
        mov al, [bx+NAME_BUF]
        call nw_case
        call nw_store
        jmp .done
.left:  cmp byte [NAME_POS], 0
        je .landed
        push byte 8                     ; back one column, as stock
        FCALL T_B1B1_0036
        add sp, 2
        dec byte [NAME_POS]
        jmp .landed
.right: mov al, [NAME_LEN]
        dec al
        cmp [NAME_POS], al
        jge .landed
        mov bl, [NAME_POS]
        xor bh, bh
        mov al, [bx+NAME_BUF]
        cbw
        push ax                         ; reprint and step right, as stock
        FCALL T_B1B1_0036
        add sp, 2
        inc byte [NAME_POS]
.landed:
        mov bl, [NAME_POS]
        xor bh, bh
        mov al, [bx+NAME_BUF]
        mov [NAME_ORIG], al
        cmp byte [cs:nw_lock], 0
        jne .done
        mov al, 0                       ; title case: capital at a word start
        or bx, bx
        jz .case
        mov ah, [bx+NAME_BUF-1]
        cmp ah, ' '
        je .case
        cmp ah, '_'
        je .case
        cmp ah, '-'
        je .case
        inc ax
.case:  mov [CASE_SMALL], al
.done:  xor di, di
        FJMP T_B261_01FB

; FAR, in place of 04D5:0316 (MOV [E436],0 / RETF): every field entry starts
; in capitals with no case lock.
nw_reset_case:
        mov byte [CASE_SMALL], 0
        mov byte [cs:nw_lock], 0
        retf

; AX = +1 or -1: step the character at the cursor through the set.
; Changes AX, BX, CX, DX and flags.
nw_turn:
        push si
        mov si, ax
        mov bl, [NAME_POS]
        xor bh, bh
        mov al, [bx+NAME_BUF]
        call nw_index
        add cx, si
        jns .not_below
        add cx, NW_SET
.not_below:
        cmp cx, NW_SET
        jb .in
        sub cx, NW_SET
.in:    call nw_char
        call nw_case
        call nw_store
        pop si
        ret

; AL = character: CX = its place in the set; anything else counts as the space.
nw_index:
        cmp al, 'a'
        jb .upper
        cmp al, 'z'
        ja .upper
        sub al, 0x20
.upper: xor cx, cx
        mov cl, al
        sub cl, 'A' - 1
        cmp al, 'A'
        jb .digit
        cmp al, 'Z'
        jbe .r
.digit: mov cl, al
        sub cl, '0' - 27
        cmp al, '0'
        jb .symbol
        cmp al, '9'
        jbe .r
.symbol:
        mov bx, NW_SYMS
.s:     cmp al, [bx]
        je .found
        inc bx
        cmp bx, NW_SYMS + NW_NSYMS
        jb .s
        xor cx, cx
        ret
.found: lea cx, [bx - NW_SYMS + 37]
.r:     ret

; CX = place in the set: AL = character.  Changes BX.
nw_char:
        mov al, ' '
        jcxz .r
        mov al, cl
        add al, 'A' - 1
        cmp cx, 26
        jbe .r
        add al, '0' - 'A' - 26
        cmp cx, 36
        jbe .r
        mov bx, cx
        mov al, [bx + NW_SYMS - 37]
.r:     ret

; AL = character: letters take the case of [CASE_SMALL].
nw_case:
        cmp al, 'a'
        jb .up
        cmp al, 'z'
        ja .r
        sub al, 0x20
.up:    cmp al, 'A'
        jb .r
        cmp al, 'Z'
        ja .r
        cmp byte [CASE_SMALL], 0
        je .r
        add al, 0x20
.r:     ret

; AL = character: it replaces the one at the cursor, on screen too; the
; cursor stays.  Changes AX, BX and flags.
nw_store:
        mov bl, [NAME_POS]
        xor bh, bh
        mov [bx+NAME_BUF], al
        mov [NAME_ORIG], al
        cbw
        push ax
        FCALL T_B1B1_0036
        add sp, 2
        push byte 8
        FCALL T_B1B1_0036
        add sp, 2
        ret

nw_lock: db 0                           ; 1 after Up or Down until the next field entry

; Extra Settings page 2 (xparams316.inc xp_extra_screen).  Kept here, at the
; end of the cave, so the page-2 additions do not move the earlier modules.
; Per row as xp_rows: row, polarity (1 = stored inverted), DS offset, label.
xp_rows2:
        db 1, 1
        dw NW_OFF, xp_s_name_wheel
        db 0
xp_page: db 0                           ; 0 page 1, 1 page 2
; Screen text is PMONEY's own.
xp_s_more:       db "<Do it>                           <More>", 0
xp_s_title2:     db "Extra Settings 2", 0
xp_s_name_wheel: db "Spell names with the data wheel:     ", 0
xp_s_doit2:      db "<Do it>                           <Back>", 0
