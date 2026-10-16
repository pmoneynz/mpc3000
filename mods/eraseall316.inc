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
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_keys
        FCALL T_B1B1_005B
        add sp, 4
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
        FCALL T_B1B1_0002               ; clear the text screen
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_title
        FCALL T_B509_2289               ; field list reset, title
        add sp, 4
        push byte 0
        push byte 2
        FCALL T_B1B1_0026               ; row 2
        add sp, 4
        mov bl, [DISK_INDEX]            ; "Disk:%s" with the stock label
        xor bh, bh
        shl bx, 2
        push word [bx+DISK_LABELS+2]
        push word [bx+DISK_LABELS]
        push ds
        push S_DISK_FMT
        FCALL T_B1BC_01EE
        add sp, 8
        push byte 0
        push byte 3
        FCALL T_B1B1_0026
        add sp, 4
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_ask
        FCALL T_B1B1_005B
        add sp, 4
        push byte 0
        push byte 4
        FCALL T_B1B1_0026
        add sp, 4
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_ask2
        FCALL T_B1B1_005B
        add sp, 4
        FCALL T_B77C_20C5               ; rule, cursor (7,0)
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_confirm
        FCALL T_B1B1_005B
        add sp, 4
.ask:   push byte 1                     ; Soft Key 1 only
        FCALL T_B060_035D
        add sp, 2
        mov dx, ax
        or ax, ax
        jz .ask
        cmp dx, 0x78
        jne .done                       ; a mode key: leave with it
        push byte 0
        push byte 7
        FCALL T_B1B1_0026
        add sp, 4
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_stop
        FCALL T_B1B1_005B
        add sp, 4
        FCALL T_D6E0_008B               ; drop queued soft keys (a repeated confirm)
        push byte 0
        FCALL T_CF0C_0006               ; INT 41 AX=0, as before the stock erase
        add sp, 2
        push ss
        lea ax, [bp-0x1C]
        push ax
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_all
        FCALL T_CEE6_0175               ; find first
        jmp .found
.next:  push ss
        lea ax, [bp-0x1C]
        push ax
        push strict word CAVE_SEG
        RELOC_PREV
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
        push byte 0
        push byte 5
        FCALL T_B1B1_0026               ; row 5
        add sp, 4
        push ss
        lea ax, [bp-0x32]
        push ax
        push strict word CAVE_SEG
        RELOC_PREV
        push era_s_busy
        FCALL T_B1BC_01EE               ; "Erasing NAME.EXT"
        add sp, 8
        push byte 40
        FCALL T_B1FF_000C               ; blank the rest of the row
        add sp, 2
        push ss
        push si
        FCALL T_CEE6_00C2               ; delete
        add sp, 4
        or ax, ax
        jz .poll
        push ax                         ; first error: stock box, stop
        FCALL T_B3C7_0007
        add sp, 2
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
era_s_confirm: db "<Erase all>", 0
era_s_stop:    db "<Stop>     ", 0
era_s_busy:    db "Erasing %s", 0
era_s_all:     db "???????????????????", 0      ; 19: the stock load-list pattern
