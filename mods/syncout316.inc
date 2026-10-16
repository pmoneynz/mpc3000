; Sync out to all four MIDI outputs: Vailixi 3.50's "MIDI clock / MIDI time code
; to all 4 outputs" (F8/F9) on OS 3.16 (PMONEY cave, PROFILE_316 only).
; Hooks: mods/WAVE316.args (sync out).
;
; Model.  The stock port bytes SO_CLK_PORT [7EAA] and SO_MTC_PORT [8310] (parameter
; block +249h / +6AFh, NVRAM page 61 and .PAR files shared with every stock OS)
; only ever hold stock values 0..4.  "All four" is stored as OUT A (1) plus a bit in
; SO_ALL [831E] (bit 0 clock, bit 1 time code), a byte of the block's zeroed
; reserve: stock code never reads it, Init PAR and stock-saved .PAR files clear it.
; Effective port = 5 (all) when the stock byte is 1 and its bit is set.  Vailixi
; keeps the value 5 itself in its own block; a stock OS would index past its
; tables with it.

; JMPF from the real-time sender 3286:0086 (Vailixi DC5B:0088), replacing
;   CMP BYTE [9331],0 / JNZ 00B4   (7 bytes; 2 NOPs follow the JMPF).
; In: BL = port 0..5 (0 off, 1-4 OUT A-D, 5 all four), CL = byte, DS = DGROUP,
; caller's CALLF frame.  Out: as stock.  Clobbers AX, BX, DX, flags (stock: the
; same).  CL kept.  Called with IF = 0 from the tick ISR (MTC before its STI,
; F8 after its CLI) and with IF = 1 from the UI task (start/stop/continue).
so_rt_send:
        cmp byte [SO_ERR], 0
        jne .ret
        sub bh, bh
        cmp bl, 5
        je .all
        ja .ret                         ; stock would index past its tables
        FJMP T_DC5B_0097                ; dec bx / js 00B4 / ...: stock single port, RETF
.ret:   retf
        ; All four outputs under one interrupt-off section: the byte lands in
        ; every ring before any tick can queue another (same order on every
        ; output), and the tick ISR, which already runs with IF = 0 here,
        ; pays no far calls.  Each ring insert is T_DA09_0000 (3033:000E)
        ; inline: [bx] capacity, [bx+2] count, [bx+4] put index (counts down,
        ; wraps at 0), data at [bx+8]; a full ring drops the byte, as stock.
.all:   push si
        pushf
        cli
        mov bx, SO_RTQ                  ; real-time queues OUT A..D, 18h bytes apart
.q:     mov ax, [bx]
        mov si, [bx+2]
        cmp si, ax
        jae .full
        inc si
        mov [bx+2], si
        mov si, [bx+4]
        or si, si
        jnz .put
        mov si, ax
.put:   dec si
        mov [bx+4], si
        mov [bx+si+8], cl
.full:  add bx, 0x18
        cmp bx, SO_RTQ + 4*0x18
        jb .q
        mov bx, SO_TXSH                 ; TE7774 control shadows, one per output
        mov dx, 0xC6
.o:     or byte [bx], 2                 ; transmitter interrupt on, as the stock path
        mov al, [bx]
        out dx, al
        inc bx
        add dx, 8                       ; C6, CE, D6, DE
        cmp dl, 0xE6
        jb .o
        popf
        pop si
        retf

; CALLF from the tick ISR 2C45:0851 (Vailixi D61A:084F, CL = F8h) and from the
; transport sender 32C6:012A (Vailixi DCA2:0128, CL = FAh/FBh/FCh), replacing
;   MOV BL,[7EAA] [/ XOR BH,BH] / CALLF 3286:0086   (11 / 9 bytes; NOPs follow).
; Port 0 (off) returns at once with BX = FFFF, as the stock sender does for it
; (SUB BH,BH / DEC BX / JS: RETF), without the far jump into it.
so_clk_send:
        mov bl, [SO_CLK_PORT]
        or bl, bl
        jz .off
        cmp bl, 1
        jne so_rt_send
        test byte [SO_ALL], 1
        jz so_rt_send
        mov bl, 5
        jmp so_rt_send
.off:   mov bx, 0xFFFF
        retf

; CALLF from the tick ISR's two MTC sends 2C45:0208 (F1h) and 2C45:021B (the quarter
; frame) (Vailixi D61A:0206 / 0219), replacing CALLF 3286:0086 with BL = [7038], the
; stock MTC port byte [8310] that 2C45:0149 copies each frame.  The effective port
; is decided here, only when a quarter frame is sent, instead of on every tick at
; 2C45:013B: OUT A plus SO_ALL bit 1 means all four.  [7038] has that one writer
; and these two readers (3.16 image 0x2C599, 0x2C652, 0x2C667).
so_mtc_send:
        cmp bl, 1
        jne so_rt_send
        test byte [SO_ALL], 2
        jz so_rt_send
        mov bl, 5
        jmp so_rt_send

; CALLF from the pending-MIDI routine 30C6:035C (Vailixi DA9B:035E), replacing
;   CALLF 3286:0039   for the Song Position Pointer (port word, count 3, buffer).
; Same arguments (caller pops).  With "all four" the pointer goes to each output
; (Vailixi passes 5 to the buffer sender, which has no all-ports case: spec D-1).
so_spp:
        push bp
        mov bp, sp
        mov al, [bp+12]
        cmp al, 5                       ; a stray 5 (Vailixi block) is all four too
        je .all
        ja .drop                        ; not a port: the stock sender would misindex
        cmp al, 1
        jne .one
        test byte [SO_ALL], 1
        jz .one
.all:   push si
        mov si, 4
.l:     push si                         ; OUT D .. OUT A
        push word [bp+10]
        push word [bp+8]
        push word [bp+6]
        FCALL T_DC5B_003B
        add sp, 8
        dec si
        jnz .l
        pop si
        pop bp
        retf
.one:   pop bp
        FJMP T_DC5B_003B
.drop:  xor ax, ax
        pop bp
        retf

; CALLF from the Sync screen 1E9A:0388 / 1E9A:0456 (Vailixi CD75:0383 / 0451),
; replacing the stock MIDI clock / MIDI time code choice field (22 bytes; NOPs
; follow).  The field edits a cave shadow 0..5 over six labels; so_sync_keys
; writes it back.  In: DS = DGROUP.  Clobbers AX, BX, DX, flags (the replaced
; field add clobbered AX..DX).
so_clk_field:
        mov al, [SO_CLK_PORT]
        mov ah, 1
        mov bx, so_shadow
        mov dx, SO_LBL_CLK
        jmp so_field
so_mtc_field:
        mov al, [SO_MTC_PORT]
        mov ah, 2
        mov bx, so_shadow+2
        mov dx, SO_LBL_MTC
so_field:
        cmp al, 5
        jb .stock
        je .put                         ; 5: a Vailixi block, shown as all four
        mov al, 0                       ; not a port: shown OFF
        jmp .put
.stock: cmp al, 1
        jne .put
        test [SO_ALL], ah
        jz .put
        mov al, 5
.put:   mov [cs:bx], al
        push byte 5                     ; field width, as stock
        push cs
        push so_ports
        push cs
        push bx
        push ds
        push dx
        FCALL T_B354_01C6
        add sp, 14
        retf

; CALLF from the Sync screen 1E9A:0689 (Vailixi CD75:0684), replacing
;   CALLF 02D7:0357   the field editor key loop (one word argument, caller pops).
; Same result in AX (AL 0 = a field was committed, else the key); then both
; shadows are written back.
so_sync_keys:
        push bp
        mov bp, sp
        push word [bp+6]
        FCALL T_B060_035D
        add sp, 2
        push ax
        mov al, [cs:so_shadow]
        mov bx, SO_CLK_PORT
        mov ah, 1
        call so_proj
        mov al, [cs:so_shadow+2]
        mov bx, SO_MTC_PORT
        mov ah, 2
        call so_proj
        pop ax
        pop bp
        retf

; Near.  AL = shown value 0..5, BX = its stock byte, AH = its SO_ALL bit.
; 5 is stored as OUT A plus the bit.  Requests the NVRAM save when anything
; changes.  Clobbers AX, DX, flags.
so_proj:
        mov dl, [SO_ALL]
        mov dh, dl
        or dl, ah
        cmp al, 5
        je .all
        xor dl, ah
        jmp .cmp
.all:   mov al, 1
.cmp:   cmp [bx], al
        jne .w
        cmp dl, dh
        je .r
.w:     pushf
        cli                             ; the tick ISR reads both bytes
        mov [bx], al
        mov [SO_ALL], dl
        popf
        mov byte [TC_NV_DIRTY], 1       ; NVRAM save of the parameter block
.r:     ret

; Choice labels: the stock five, then 3.16's own "ALL" (Edit Sound Play X list).
so_ports:
        dw SO_STR_OFF, DGROUP_SEG
        RELOC_PREV
        dw SO_STR_OUT_A, DGROUP_SEG
        RELOC_PREV
        dw SO_STR_OUT_A+6, DGROUP_SEG
        RELOC_PREV
        dw SO_STR_OUT_A+12, DGROUP_SEG
        RELOC_PREV
        dw SO_STR_OUT_A+18, DGROUP_SEG
        RELOC_PREV
        dw SO_STR_ALL, DGROUP_SEG
        RELOC_PREV
        dd 0
so_shadow: db 0, 0, 0, 0                ; clock at +0, time code at +2 (byte fields)
