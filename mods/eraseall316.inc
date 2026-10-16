; Disk -> 7 -> Erase a File: Soft Key 2 erases every file in the current
; directory (root of the floppy or of the selected SCSI partition), ported from
; Vailixi 3.50 (screen B5C4:0003 = B509:0BB3, engine B766:0003 = B509:25D3;
; file 0x35C43 / 0x37663).  OS 3.16 only (PROFILE_316).  Port spec: Vailixi
; port notes in notes/vailixi_features.md.  Screen text is PMONEY's own.
;
; WAVE316.args:
;   0x83E7  push ds / push 2666h / CALLF 0427:0065 / add sp,4 / push 1
;           -> CALLF era_keys / 7 x NOP / push 2  (Soft Keys 1 and 2 accepted)
;   0x8403  cmp dx,78h / jnz 0C73h -> JMPF era_dispatch
;
; Deviations from Vailixi: a confirmation page (Soft Key 1 confirms); *.SYS
; files are kept (the PMONEY boot file); the first delete error stops the
; loop and shows the stock error box; the status row is blanked to column 40
; and shows NAME.EXT; INT 41 AX=0 runs once first, as before the stock
; single-file erase.

ERA_STOP_KEY equ 0x78                   ; Soft Key 1 <Stop> during the loop (Vailixi: 0x78)
%define ERA_KEEP_SYS                    ; owner decision D-3: keep *.SYS (drop to erase them too)

; FAR, from 077D:0C17 in place of the stock soft-key row.  Keeps BP, SI, DI.
era_keys:
        mov bx, era_s_keys
        call du_put
        retf

; JMP from 077D:0C33.  DX = key (non-zero) from the field editor; frame of
; 077D:0BB7 (BP; [bp+6] far raw file name; no SI/DI saved).  DS = DGROUP.
era_dispatch:
        cmp dx, 0x78
        jne .not_one
        FJMP T_B509_0C34                ; stock <Erase it> arm (077D:0C38)
.not_one:
        cmp dx, 0x79
        jne .leave
        call era_all                    ; DX = 0 done, else the key that left
.leave: mov ax, dx                      ; the stock tail (077D:0C73)
        leave
        retf

; NEAR.  Confirmation page, then the erase loop.  Returns DX = 0 (the load
; screen re-reads the directory) or a key that left the confirmation page.
; Frame: [bp-1Ch] 27-byte find record (raw name at +7), [bp-32h] 22-byte
; display name.  Keeps SI, DI, BP, DS.
era_all:
        push bp
        mov bp, sp
        sub sp, 0x32
        push si
        push di
        mov bx, era_s_title
        call du_title                   ; field list reset, clear, title
        mov al, 2
        call du_at                      ; row 2
        mov bl, [DISK_INDEX]            ; "Disk:%s" with the stock label
        xor bh, bh
        shl bx, 2
        push word [bx+DISK_LABELS+2]
        push word [bx+DISK_LABELS]
        push ds
        push S_DISK_FMT
        FCALL T_B1BC_01EE
        add sp, 8
        mov al, 3
        mov bx, era_s_ask
        call du_row_put
        mov al, 4
        mov bx, era_s_ask2
        call du_row_put
        FCALL T_B77C_20C5               ; rule, cursor (7,0)
        mov bx, era_s_confirm
        call du_put
        mov ax, 1                       ; Soft Key 1 only
        call du_key
        mov dx, ax
        jne .done                       ; a mode key: leave with it
        mov al, 7
        mov bx, era_s_stop
        call du_row_put
        FCALL T_D6E0_008B               ; drop queued soft keys (a repeated confirm)
        call du_reset                   ; INT 41 AX=0, as before the stock erase
        push ss
        lea ax, [bp-0x1C]
        push ax
        push cs
        push era_s_all
        FCALL T_CEE6_0175               ; find first
        jmp .found
.next:  push ss
        lea ax, [bp-0x1C]
        push ax
        push cs
        push era_s_all
        FCALL T_CEE6_01E1               ; find next
.found: add sp, 8
        or ax, ax
        jnz .end                        ; no more files (or a find error)
        lea si, [bp-0x1C+7]             ; raw name: 8 or 16 chars + 3 ext + NUL
%ifdef ERA_KEEP_SYS
        lea bx, [si+8]                  ; short/long test as the stock formatter 077D:194D
        cmp byte [ss:si+11], 0
        je .ext
        lea bx, [si+16]
.ext:   cmp word [ss:bx], 'SY'          ; keep *.SYS (the PMONEY boot file)
        jne .erase
        cmp byte [ss:bx+2], 'S'
        je .next
.erase:
%endif
        push ss
        lea ax, [bp-0x32]
        push ax
        push ss
        push si
        FCALL T_B509_21A1               ; NAME.EXT for display
        add sp, 8
        mov al, 5
        call du_at                      ; row 5
        push ss
        lea ax, [bp-0x32]
        push ax
        push cs
        push era_s_busy
        FCALL T_B1BC_01EE               ; "Erasing NAME.EXT"
        add sp, 8
        call du_eol                     ; blank the rest of the row
        push ss
        push si
        FCALL T_CEE6_00C2               ; delete
        add sp, 4
        or ax, ax
        jz .poll
        call du_err                     ; first error: stock box, stop
        jmp .end
.poll:  FCALL T_D6F3_000E               ; keys queued?
        or ax, ax
        jz .next
        FCALL T_D6E0_0000               ; take one (others are discarded)
        cmp al, ERA_STOP_KEY
        jne .next
.end:   xor dx, dx
.done:  pop di
        pop si
        leave
        ret

; PMONEY wording.  Rows are at most 40 columns.
era_s_keys:    db "<Erase it> <Erase all>", 0
era_s_title:   db "Erase All Files", 0
era_s_ask:     db "Erase every file on this disk?", 0
era_s_ask2:    db "(.SYS files are kept. No undo.)", 0
era_s_confirm  equ era_s_keys + 11                 ; "<Erase all>", the tail of era_s_keys
era_s_stop:    db "<Stop>     ", 0
era_s_busy:    db "Erasing %s", 0
era_s_all:     db "???????????????????", 0      ; 19: the stock load-list pattern
