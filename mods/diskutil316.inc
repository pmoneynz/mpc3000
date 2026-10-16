; Vailixi 3.50 disk utilities on OS 3.16 (PMONEY cave, PROFILE_316 only):
;   H6   mount PC-readable ("hybrid") SCSI disks       (Vailixi D470:065C..0723)
;   F15  create them: Format Hard Disk layout page    (Vailixi B509:15D3..1993, D3CB:0095..0A5B)
;   F16  32 MB sound in one file = F15 option 5 + H6
;   F11  copy one SCSI disk onto another, Disk 9 5    (Vailixi B509:1DCC = B6E5:000C)
;   F14  <Zero>: software low-level format            (Vailixi B509:10BC <Soft>, D3CB:089E)
; Port spec and deviations: notes/vailixi_features.md (F11, F14, F15, F16).
; Screen text is PMONEY's own.  On-disk identifiers that a reader tests (EBR 10h
; bytes, CA FE 20 07, 55 AA, the MBR fields of D4) are Vailixi's; the OEM name,
; volume labels and serials, which no MPC reader tests, are PMONEY's.
;
; Hooks (WAVE316.args form):
;   --patch=86de:c746fe0400:c746fe0500                                   menu: 5 items
;   --patch=8713:1e6886279a6500270483c404:9a{cfo_items}90909090909090    menu: item 5 text
;   --patch=874f:83fb037729:ea{cfo_dispatch}                             menu: item 5 dispatch
;   --patch=8958:1e68be299a6500270483c404:9a{fmt_keys}90909090909090     format: <Zero> key text
;   --patch=8969:6a02:6a03                                               format: 3 soft keys
;   --patch=897e:3d7900746ae94502:ea{fmt_dispatch}909090                 format: <Fast>/<Zero>
;   --patch=89f9:c606b7d460:ea{part_mode}                                format: layout page
;   --patch=2b0bd:6a6168050d:ea{mnt_hybrid}                              partition reader
;
; Every destructive action has a confirmation page: queued soft keys are dropped
; (T_D6E0_008B), then only Soft Key 1 confirms.  Sector I/O uses 512-byte blocks
; and LBAs below 2^21 (the READ(6)/WRITE(6) CDB of 2AB2:00FF wraps above).

DU_CYL      equ 16065               ; 255 x 63 sectors: hybrid stride unit (Vailixi 3EC1h)
DU_LBA_HI   equ 0x20                ; 2^21 blocks, as DX: the 6-byte CDB's LBA limit
DU_CHUNK    equ 9                   ; blocks per command (Vailixi copier), 4,608 bytes of SND_SEG

; ======================================================================= shared helpers

; ES:BX = sector.  ZF = 1: CA FE 20 07 at 1B8h and 55 AA at 1FEh (Vailixi D470:06A0..06C4).
du_sig: cmp word [es:bx+0x1B8], 0xFECA
        jne .r
        cmp word [es:bx+0x1BA], 0x0720
        jne .r
        cmp word [es:bx+0x1FE], 0xAA55
.r:     ret

; ES:BX = LBA 0.  ZF = 1: hybrid MBR (D4): 55 AA, entry 1 = type 05 starting at LBA 63.
du_mbr: cmp word [es:bx+0x1FE], 0xAA55
        jne .r
        cmp byte [es:bx+0x1C2], 5
        jne .r
        cmp word [es:bx+0x1C6], 63
        jne .r
        cmp word [es:bx+0x1C8], 0
.r:     ret

; ES = SND_SEG: zero the sector buffer ES:0000..01FF.  Clobbers AX, CX.
du_zero:
        push di
        xor di, di
        xor ax, ax
        mov cx, 256
        cld
        rep stosw
        pop di
        ret

; Write SND_SEG:0000 (one block) to LBA DX:AX of the active unit.  AX = 0 / SCSI code, ZF.
; Keeps ES.  Clobbers BX, CX, DX.
du_write:
        push es                     ; far C calls need not keep ES
        push strict word SND_SEG
        RELOC_PREV
        push byte 0
        push byte 1
        push dx
        push ax
        push word [SCSI_ACTIVE]
        FCALL T_D470_02D5
        add sp, 12
        pop es
        or ax, ax
        ret

; The active unit's sectors changed under the OS: mark the media changed and scan
; again (as 077D:13DE after the stock partition writer).  AX = scan result.
du_rescan:
        mov byte [SCSI_CHANGED], 1
        FCALL T_D470_0458
        mov [SCSI_STATUS], al
        ret

; Copy (SI = source unit) or zero-fill (SI = -1; SND_SEG:0000 holds DU_CHUNK zero
; blocks) DX:AX blocks from LBA 0 onto unit DI, DU_CHUNK per command through
; SND_SEG:0000.  Row 5 column 30 shows the percentage; Soft Key 1 stops between
; commands.  Out: AX = 0 done, 1 stopped, else the SCSI code of the failed command.
xfer:   push bp
        mov bp, sp
        sub sp, 16
        mov [bp-4], ax              ; [bp-2]:[bp-4] remaining
        mov [bp-2], dx
        mov [bp-12], ax             ; [bp-10]:[bp-12] total
        mov [bp-10], dx
        xor ax, ax
        mov [bp-8], ax              ; [bp-6]:[bp-8] next LBA
        mov [bp-6], ax
        dec ax
        mov [bp-14], ax             ; last percentage shown
        FCALL T_D6E0_008B           ; drop queued soft keys (the confirming press)
.loop:  mov ax, [bp-4]
        or ax, [bp-2]
        jz .ret
        xor cx, cx                  ; (MOV CX,9 would hold a segment-valued word)
        mov cl, DU_CHUNK
        cmp word [bp-2], 0
        jne .n
        cmp [bp-4], cx
        jae .n
        mov cx, [bp-4]
.n:     mov [bp-16], cx
        or si, si
        js .w
        push strict word SND_SEG
        RELOC_PREV
        push byte 0
        push cx
        push word [bp-6]
        push word [bp-8]
        push si
        FCALL T_D470_02B5
        add sp, 12
        or ax, ax
        jnz .ret
.w:     push strict word SND_SEG
        RELOC_PREV
        push byte 0
        push word [bp-16]
        push word [bp-6]
        push word [bp-8]
        push di
        FCALL T_D470_02D5
        add sp, 12
        or ax, ax
        jnz .ret
        mov ax, [bp-16]
        sub [bp-4], ax
        sbb word [bp-2], 0
        add [bp-8], ax
        adc word [bp-6], 0
        mov ax, [bp-8]              ; percentage = done * 100 / total
        mov dx, [bp-6]
        mov bx, 100
        xor cx, cx
        FCALL T_F800_20C4
        push word [bp-10]
        push word [bp-12]
        push dx
        push ax
        FCALL T_F800_2101           ; unsigned, callee pops
        cmp ax, [bp-14]
        je .poll
        mov [bp-14], ax
        push byte 30
        push byte 5
        FCALL T_B1B1_0026
        push word [bp-14]
        push cs
        push xf_s_pct
        FCALL T_B1BC_01EE
        add sp, 10
.poll:  FCALL T_D6F3_000E           ; keys queued?
        or ax, ax
        jz .loop
        FCALL T_D6E0_0000           ; take one; others are discarded
        cmp al, 0x78
        jne .loop
        mov ax, 1
.ret:   leave
        ret

xf_s_pct:  db "%3d%%", 0
xf_s_stop: db "<Stop>", 0

; ======================================================================= F11 SCSI disk copier

; CALLF from the Copy/Format/Other menu 077D:0F43 (image 0x8713) in place of the
; item 4 print (PUSH DS / PUSH 2786h / CALLF 0427:0065 / ADD SP,4; 7 NOPs follow).
; Keeps BP, SI, DI, DS.
cfo_items:
        push ds
        push S_MENU_ITEM4
        FCALL T_B1B1_005B
        add sp, 4
        mov bx, cfo_s_item5
        call du_put
        retf

; JMPF from 077D:0F7F (image 0x874F) in place of CMP BX,3 / JA 0FADh.  BX = choice-1
; (the menu's max is now 5), DX = 0; frame of 077D:0F03 (BP, 4 bytes of locals).
cfo_dispatch:
        cmp bx, 3
        ja .more
        FJMP T_B509_0FB3            ; stock items 1-4: shl bx,1 / jmp [cs:bx+0FB1h]
.more:  cmp bx, 4
        jne .out
        call sdc_copy
        mov dx, ax
.out:   mov ax, dx                  ; the stock tail 077D:0FAD
        leave
        retf

; NEAR.  Unit page, checks (C1-C3), confirmation (C4), copy with <Stop> (C5), rescan
; when the target is the active unit (C6).  Out: AX = [MODE] or the key that left.
; Frame: [bp-2] source, [bp-4] target, [bp-6]:[bp-8] target capacity,
; [bp-10]:[bp-12] blocks to copy, [bp-14] saved [SCSI_BLKSIZE], [bp-16] saved [SCSI_DEVTYPE].
sdc_copy:
        push bp
        mov bp, sp
        sub sp, 16
        push si
        push di
        mov ax, [SCSI_BLKSIZE]
        mov [bp-14], ax
        mov al, [SCSI_DEVTYPE]
        mov [bp-16], al
        mov ax, [SCSI_ACTIVE]       ; source: the active unit, target: the next one
        call .clamp
        mov [bp-2], ax
        inc ax
        call .clamp
        mov [bp-4], ax
.page:  mov bx, sdc_s_title
        call du_title
        mov al, 1
        call du_at
        mov bx, sdc_s_info
        call du_put
        mov cl, 4
        lea ax, [bp-2]
        mov bx, sdc_s_from
        call .field
        mov cl, 5
        lea ax, [bp-4]
        mov bx, sdc_s_to
        call .field
        FCALL T_B77C_20EA           ; rule, "<Do it>"
        mov ax, 1
        call du_key
        jne .leave
        mov byte [SCSI_DEVTYPE], 0  ; 512-byte blocks for every command below (R4)
        mov bx, sdc_s_same          ; C1
        mov ax, [bp-2]
        cmp ax, [bp-4]
        je .msg
        push word [bp-4]
        FCALL T_D470_03AD           ; target capacity
        add sp, 2
        mov bx, sdc_s_nodst
        call .cap                   ; C2
        jz .msg
        mov [bp-8], ax
        mov [bp-6], dx
        push word [bp-2]
        FCALL T_D470_03AD           ; source capacity ([SCSI_BLKSIZE] now the source's)
        add sp, 2
        mov bx, sdc_s_nosrc
        call .cap
        jz .msg
        call sdc_extent             ; C3: DX:AX = blocks the source layout uses
        mov [bp-12], ax
        mov [bp-10], dx
        mov bx, sdc_s_small         ; target smaller than that: refuse (Vailixi truncates)
        cmp dx, [bp-6]
        ja .msg
        jb .conf
        cmp ax, [bp-8]
        ja .msg
.conf:  mov bx, sdc_s_title         ; C4
        call du_title
        mov al, 2
        call du_at
        push word [bp-4]
        push word [bp-2]
        push cs
        push sdc_s_ask
        FCALL T_B1BC_01EE
        add sp, 8
        mov al, 3
        call du_at
        push word [bp-4]
        push cs
        push sdc_s_lost
        FCALL T_B1BC_01EE
        add sp, 6
        mov bx, sdc_s_keys
        call du_ask
        jnz .leave
        call du_reset
        mov al, 5
        call du_at
        mov bx, sdc_s_busy
        call du_put
        mov bx, xf_s_stop
        call du_keys
        mov si, [bp-2]
        mov di, [bp-4]
        mov ax, [bp-12]
        mov dx, [bp-10]
        call xfer                   ; C5
        cmp ax, 1
        jbe .end
        call du_box
.end:   call .rest
        cmp di, [SCSI_ACTIVE]       ; C6
        jne .mode
        call du_rescan
.mode:  mov al, [MODE]
        cbw
        jmp .out
.msg:   call .rest                  ; BX = refusal: row 3, <Back> to the unit page
        mov al, 3
        call du_at
        call du_put
        call du_eol
        mov bx, sdc_s_back
        call du_keys
        mov ax, 1
        call du_key
        je .page
.leave: call .rest
.out:   pop di
        pop si
        leave
        ret
.rest:  push ax                     ; restore the active unit's block size and type
        mov ax, [bp-14]
        mov [SCSI_BLKSIZE], ax
        mov al, [bp-16]
        mov [SCSI_DEVTYPE], al
        pop ax
        ret
.cap:   cmp word [SCSI_BLKSIZE], 512 ; ZF = 1: no disk, or not 512-byte blocks
        jne .c1
        mov cx, ax
        or cx, dx
        ret
.c1:    cmp ax, ax
        ret
.clamp: or ax, ax
        jns .c2
        xor ax, ax
.c2:    cmp ax, 6
        jbe .c3
        mov ax, 6
.c3:    ret
.field: push ax                     ; CL = row, AX = SS offset of the unit word, BX = label
        mov al, cl
        call du_at
        pop ax
        push byte 0                 ; flags
        push byte 6                 ; max
        push byte 0                 ; min
        push byte 1                 ; width
        push ss
        push ax
        push cs
        push bx
        FCALL T_B354_03B1
        add sp, 16
        ret

; NEAR, BP = sdc_copy's frame.  DX:AX = source capacity.  Out: DX:AX = the blocks the
; source layout uses: MPC (55 AA at 1FCh): last table entry + the word at 13h; hybrid
; MBR (D4): 63 + the extended length; else (or LBA 0 unreadable) the capacity.  Never
; more than the capacity or 2^21.  Reads LBA 0 into SND_SEG:0000.
sdc_extent:
        push es
        push dx
        push ax
        mov ax, strict word SND_SEG
        RELOC_PREV
        mov es, ax
        push es
        push byte 0
        push byte 1
        push byte 0
        push byte 0
        push word [bp-2]
        FCALL T_D470_02B5
        add sp, 12
        push strict word SND_SEG    ; far C calls need not keep ES
        RELOC_PREV
        pop es
        or ax, ax
        jnz .cap
        xor bx, bx
        cmp word [es:0x1FC], 0xAA55
        jne .hyb
        mov bx, 0x40                ; MPC: 26 volume starts at 40h, entry 0 always
.t:     cmp bx, 0x40+25*4
        jae .last
        mov ax, [es:bx+4]
        or ax, [es:bx+6]
        jz .last
        add bx, 4
        jmp .t
.last:  mov ax, [es:bx]
        mov dx, [es:bx+2]
        add ax, [es:0x13]
        adc dx, 0
        jmp .min
.hyb:   call du_mbr
        jne .cap
        mov ax, [es:0x1CA]
        mov dx, [es:0x1CC]
        add ax, 63
        adc dx, 0
.min:   pop bx                      ; CX:BX = capacity
        pop cx
        cmp dx, cx
        ja .use_cap
        jb .lim
        cmp ax, bx
        jbe .lim
.use_cap:
        mov ax, bx
        mov dx, cx
        jmp .lim
.cap:   pop ax
        pop dx
.lim:   cmp dx, DU_LBA_HI
        jb .r
        mov dx, DU_LBA_HI
        xor ax, ax
.r:     pop es
        ret

cfo_s_item5: db "5.Copy a SCSI disk to another", 0
sdc_s_title: db "Copy SCSI Disk", 0
sdc_s_info:  db "Copies the used sectors of one SCSI", 10, "disk onto another SCSI disk.", 0
sdc_s_from:  db "Copy from SCSI unit:", 0
sdc_s_to:    db "Copy onto SCSI unit:", 0
sdc_s_ask:   db "Copy SCSI unit %d onto unit %d?", 0
sdc_s_lost:  db "All data on unit %d is lost. No undo.", 0
sdc_s_keys:  db "<Copy now>", 0
sdc_s_busy:  db "Copying sectors...", 0
sdc_s_same:  db "Choose two different units.", 0
sdc_s_nodst: db "No usable disk on the target unit.", 0
sdc_s_nosrc: db "No usable disk on the source unit.", 0
sdc_s_small: db "The target disk is too small.", 0
sdc_s_back:  db "<Back>", 0

; ======================================================================= F14 <Zero>

; CALLF from Format Hard Disk 077D:1188 (image 0x8958) in place of the "<Slow> <Fast>"
; print (7 NOPs follow).  Keeps BP, SI, DI.
fmt_keys:
        mov bx, fmt_s_keys
        call du_put
        retf

; JMPF from 077D:11AE (image 0x897E) in place of CMP AX,79h / JZ 121Dh / JMP 13FBh.
; AX = SI = the key (not 0, not 78h).  Frame of 077D:1081: BP, locals [bp-2..-6], SI, DI.
fmt_dispatch:
        cmp ax, 0x79
        je .fast
        cmp ax, 0x7A
        jne fmt_tail
        call sw_zero
        or ax, ax
        jnz fmt_tail
.fast:  push ds                     ; as stock 077D:121D: title, then the layout page
        push S_FMT_TITLE
        FCALL T_B509_2289
        add sp, 4
        jmp part_mode
fmt_tail:                           ; stock 077D:13FB with AX = the result
        pop di
        pop si
        leave
        retf

; NEAR.  Confirmation, then zero every block of the active unit below min(capacity,
; 2^21).  Out: AX = 0 done (the caller continues to the layout page), else the key
; that left the confirmation page or [MODE].  Stop or error: the disk is rescanned.
sw_zero:
        push si
        push di
        push word [SCSI_ACTIVE]
        FCALL T_D470_03AD
        add sp, 2
        mov cx, ax
        or cx, dx
        jz .bad
        cmp word [SCSI_BLKSIZE], 512
        jne .bad
        cmp dx, DU_LBA_HI
        jb .keep
        mov dx, DU_LBA_HI
        xor ax, ax
.keep:  mov si, ax
        mov di, dx
        mov bx, zr_s_title
        call du_title
        mov al, 2
        call du_at
        push word [SCSI_ACTIVE]
        push cs
        push zr_s_ask
        FCALL T_B1BC_01EE
        add sp, 6
        mov al, 3
        call du_at
        mov bx, zr_s_info
        call du_put
        mov bx, zr_s_keys
        call du_ask
        jnz .ret
        call du_reset
        push es
        mov ax, strict word SND_SEG
        RELOC_PREV
        mov es, ax
        push di
        xor di, di
        xor ax, ax
        mov cx, DU_CHUNK*256
        cld
        rep stosw
        pop di
        pop es
        mov al, 5
        call du_at
        mov bx, zr_s_busy
        call du_put
        mov bx, xf_s_stop
        call du_keys
        mov ax, si
        mov dx, di
        mov si, -1
        mov di, [SCSI_ACTIVE]
        call xfer
        or ax, ax
        jz .ret
        cmp ax, 1
        je .stop
        call du_box
.stop:  call du_rescan              ; the active disk is no longer what the OS mounted
        jmp .mode
.bad:   mov ax, 0xFF51              ; the stock "format failed" box (077D:124E)
        call du_err
.mode:  mov al, [MODE]
        cbw
.ret:   pop di
        pop si
        ret

fmt_s_keys: db "<Slow>     <Fast>     <Zero>", 0
zr_s_title: db "Zero Hard Disk", 0
zr_s_ask:   db "Every sector of SCSI unit %d is set", 0
zr_s_info:  db "to zero, then you choose partitions.", 10
            db "This takes a long time. No undo.", 0
zr_s_keys:  db "<Zero now>", 0
zr_s_busy:  db "Zeroing sectors...", 0

; ======================================================================= F15 PC-readable partitions

; JMPF from 077D:1229 (image 0x89F9) in place of MOV BYTE [D4B7],60h; also from
; fmt_dispatch.  Reached after <Slow> succeeded, <Fast> and <Zero>.  Frame of
; 077D:1081, the page title drawn.
part_mode:
        mov byte [OPTION], 0x60     ; the replaced instruction
        mov al, 1
        call du_at
        mov bx, pm_s_text
        call du_put
        mov bx, pm_s_keys
        call du_keys
        mov ax, 2
        call du_key
        je .std
        cmp ax, 0x79
        jne fmt_tail
        call hyb_ui
        jmp fmt_tail
.std:   push ds                     ; the stock partition-count page, unchanged
        push S_FMT_TITLE
        FCALL T_B509_2289
        add sp, 4
        FJMP T_B509_13DE

; NEAR.  Option page, confirmation, writer, rescan.  Out: AX = [MODE] or the key
; that left.  Frame: [bp-2]:[bp-4] capacity (lo, hi), [bp-6] count, [bp-8] choice.
hyb_ui: push bp
        mov bp, sp
        sub sp, 8
        push si
        push di
        push word [SCSI_ACTIVE]
        FCALL T_D470_03AD
        add sp, 2
        mov [bp-2], ax
        mov [bp-4], dx
        mov ax, 0xFF51
        cmp word [SCSI_BLKSIZE], 512
        jne .err
        mov bx, hy_s_title
        call du_title
        xor di, di                  ; DI = last option shown
        mov si, 1
.opt:   call .count
        jz .last
        mov di, si
        push ax
        mov ax, si
        call du_at
        pop ax
        mov bx, si
        shl bx, 1
        push word [cs:bx+hy_mb-2]
        push ax
        push si
        push cs
        push hy_s_row
        FCALL T_B1BC_01EE
        add sp, 10
        inc si
        cmp si, 6
        jb .opt
.last:  mov ax, 0xFF51              ; disk too small for one volume
        or di, di
        jz .err
        FCALL T_B77C_20C5           ; rule, cursor (7,0)
        push byte 0
        push di
        push ss
        lea ax, [bp-8]
        push ax
        FCALL T_EBC8_0003           ; "Select option:" 1..DI
        add sp, 8
        or ax, ax
        jnz .out
        mov al, [bp-8]
        cbw
        mov si, ax
        mov [cs:hy_n], al
        call .count
        mov [cs:hy_cnt], al
        mov [bp-6], ax
        mov bx, hy_s_title
        call du_title
        mov al, 2
        call du_at
        mov bx, si
        shl bx, 1
        push word [cs:bx+hy_mb-2]
        push word [bp-6]
        push word [SCSI_ACTIVE]
        push cs
        push hy_s_ask
        FCALL T_B1BC_01EE
        add sp, 10
        mov al, 3
        call du_at
        mov bx, hy_s_lost
        call du_put
        mov bx, hy_s_keys
        call du_ask
        jnz .out
        mov al, 5
        call du_at
        mov bx, hy_s_busy
        call du_put
        call hyb_write
        jz .ok
        call du_box                 ; the first failed write: nothing after it is written
        jmp .mode
.ok:    call du_rescan
        or ax, ax
        mov ax, 0xFF51
        jnz .err
        mov byte [SCSI_STATUS], 0   ; as stock 077D:13F6
        jmp .mode
.err:   call du_err
.mode:  mov al, [MODE]
        cbw
.out:   pop di
        pop si
        leave
        ret
.count: mov ax, si                  ; AX = min(capacity / (SI * 16065), 26); ZF = 1 when 0
        mov cx, DU_CYL
        mul cx
        push dx
        push ax
        push word [bp-4]
        push word [bp-2]
        FCALL T_F800_2101           ; unsigned, callee pops
        or dx, dx
        jnz .26
        cmp ax, 26
        jbe .c
.26:    mov ax, 26
.c:     or ax, ax
        ret

; NEAR.  [cs:hy_n] = option n (1..5), [cs:hy_cnt] = volume count c: the layout on the
; active unit.  D1 order: LBA 0 and LBA 63 zeroed, volumes, EBRs c-1..0, the MBR
; last.  Stops at the first failed write.  Out: AX = 0 / SCSI code, ZF.
; Frame: [bp-2]:[bp-4] base = i * stride (lo, hi).
hyb_write:
        push bp
        mov bp, sp
        sub sp, 4
        push si
        push di
        push es
        mov byte [SCSI_CHANGED], 1  ; as the stock writer 2A8A:0099
        call du_reset
        mov al, [cs:hy_n]
        cbw
        mov cx, DU_CYL
        mul cx
        mov [cs:hy_stride], ax
        mov [cs:hy_stride+2], dx
        mov ax, strict word SND_SEG
        RELOC_PREV
        mov es, ax
        call du_zero
        xor ax, ax
        cwd
        call du_write               ; LBA 0: no longer an MPC or hybrid disk
        jnz .ret
        mov ax, 63
        xor dx, dx
        call du_write               ; LBA 63: no stale EBR
        jnz .ret
        xor si, si
        mov [bp-2], si
        mov [bp-4], si
.vol:   mov ax, 63                  ; V_0 = 126, V_i = i * stride + 63
        or si, si
        jnz .v1
        add ax, ax
.v1:    xor dx, dx
        add ax, [bp-2]
        adc dx, [bp-4]
        call hy_volume
        jnz .ret
        mov ax, [cs:hy_stride]
        add [bp-2], ax
        mov ax, [cs:hy_stride+2]
        adc [bp-4], ax
        inc si
        mov al, [cs:hy_cnt]
        cbw
        cmp si, ax
        jb .vol
        mov ax, [bp-2]              ; extended length = c * stride - 63
        mov dx, [bp-4]
        sub ax, 63
        sbb dx, 0
        mov [cs:hy_ext], ax
        mov [cs:hy_ext+2], dx
.ebr:   dec si                      ; EBR i at E_i = i * stride (E_0 = 63)
        mov ax, [cs:hy_stride]
        sub [bp-2], ax
        mov ax, [cs:hy_stride+2]
        sbb [bp-4], ax
        call hy_ebr
        mov ax, [bp-2]
        mov dx, [bp-4]
        or si, si
        jnz .e1
        mov ax, 63
.e1:    call du_write
        jnz .ret
        or si, si
        jnz .ebr
        call du_zero                ; the MBR
        call hy_sig
        mov word [es:0x1BF], 0x0101 ; start head 1, sector 1, cylinder 0
        mov word [es:0x1C2], 0xFE05 ; type 05, end head FEh
        mov byte [es:0x1C4], 0x3F   ; end sector 63
        mov ax, [cs:hy_ext]
        mov dx, [cs:hy_ext+2]
        mov [es:0x1CA], ax
        mov [es:0x1CC], dx
        mov cx, 63*254              ; end cylinder = length / 63 / 254 - 1 (D3CB:0550)
        div cx
        dec al
        mov [es:0x1C5], al
        mov byte [es:0x1C6], 63     ; relative start 63
        xor ax, ax
        cwd
        call du_write
.ret:   pop es
        pop di
        pop si
        leave
        ret

; ES:0000: the hybrid signature: CA FE 20 07 at 1B8h, 55 AA at 1FEh.
hy_sig: mov word [es:0x1B8], 0xFECA
        mov word [es:0x1BA], 0x0720
        mov word [es:0x1FE], 0xAA55
        ret

; NEAR.  SI = i, DX:AX = V (its first sector): boot sector, FAT1 (11), FAT2 (11),
; root directory (32) = 55 sectors.  Out: AX = 0 / SCSI code, ZF.  Clobbers DI.
hy_volume:
        push bp
        mov bp, sp
        push dx                     ; [bp-2] V hi
        push ax                     ; [bp-4] V lo
        call du_zero
        push si
        push ds
        push cs
        pop ds
        mov si, hy_bpb
        xor di, di
        mov cx, hy_bpb_end - hy_bpb
        cld
        rep movsb
        pop ds
        pop si
        mov al, 16                  ; D2: 32 sectors/cluster for n >= 4 (Vailixi: n = 5 only)
        cmp byte [cs:hy_n], 4
        jb .s
        mov al, 32
.s:     mov [es:0x0D], al
        mov ax, 0xFFFF              ; total sectors: 65,535 (n = 5)
        cmp byte [cs:hy_n], 5
        je .t
        mov ax, [cs:hy_stride]      ; else stride - 63, and 63 fewer for volume 0
        sub ax, 63
        or si, si
        jnz .t
        sub ax, 63
.t:     mov [es:0x13], ax
        mov ax, [bp-4]              ; hidden sectors = V
        mov [es:0x1C], ax
        mov ax, [bp-2]
        mov [es:0x1E], ax
        mov ax, si
        inc ax
        mov [es:0x27], al           ; serial byte 0 = i + 1
        add al, 'A'-1
        mov [es:0x2B+10], al        ; label letter
        mov [cs:hy_letter], al
        mov word [es:0x1FE], 0xAA55
        mov ax, [bp-4]
        mov dx, [bp-2]
        call du_write
        jnz .ret
        mov di, 1
.k:     call du_zero
        cmp di, 1
        je .fat
        cmp di, 12
        je .fat
        cmp di, 23
        jne .w
        push si                     ; root sector 0: the volume label entry
        push di
        push ds
        push cs
        pop ds
        mov si, hy_bpb + 0x2B
        xor di, di
        mov cx, 11
        rep movsb
        pop ds
        pop di
        pop si
        mov byte [es:11], 8         ; attribute: volume label
        mov al, [cs:hy_letter]
        mov [es:10], al
        jmp short .w
.fat:   mov word [es:0], 0xFFF8     ; D3: F8 FF FF (Vailixi and stock: F8 FF FF FF FF)
        mov byte [es:2], 0xFF
.w:     mov ax, [bp-4]
        mov dx, [bp-2]
        add ax, di
        adc dx, 0
        call du_write
        jnz .ret
        inc di
        cmp di, 55
        jb .k
        xor ax, ax
.ret:   leave
        ret

; NEAR, BP = hyb_write's frame ([bp-2]:[bp-4] = E_i base).  SI = i: EBR i in ES:0000.
hy_ebr: call du_zero
        call hy_sig
        mov byte [es:0x18], 0x10    ; read by the mount test (H6) and the BIOS geometry
        mov byte [es:0x1A], 0x10
        mov di, 0x80                ; MPC volume table: V_0 = 126, V_k = k * stride + 63
        xor ax, ax
        cwd
        mov cl, [cs:hy_cnt]
        xor ch, ch
.v:     push ax
        push dx
        add ax, 63
        adc dx, 0
        cmp di, 0x80
        jne .v2
        mov ax, 126
.v2:    mov [es:di], ax
        mov [es:di+2], dx
        pop dx
        pop ax
        add ax, [cs:hy_stride]
        adc dx, [cs:hy_stride+2]
        add di, 4
        loop .v
        mov al, [cs:hy_n]           ; entry 1: the volume (type 01)
        mov cx, si
        mul cl                      ; AX = i * n
        mov byte [es:0x1BF], 1      ; start head 2 for i = 0, else 1
        or si, si
        jnz .h
        mov byte [es:0x1BF], 2
.h:     mov byte [es:0x1C0], 1
        mov [es:0x1C1], al
        mov word [es:0x1C2], 0xFE01
        mov byte [es:0x1C4], 0x3F
        add al, [cs:hy_n]
        dec ax
        mov [es:0x1C5], al
        mov byte [es:0x1C6], 63
        mov ax, [cs:hy_stride]      ; length stride - 63, and 63 fewer for i = 0
        mov dx, [cs:hy_stride+2]
        sub ax, 63
        sbb dx, 0
        or si, si
        jnz .l
        sub ax, 63
        sbb dx, 0
.l:     mov [es:0x1CA], ax
        mov [es:0x1CC], dx
        mov al, [cs:hy_cnt]         ; entry 2 (i < c - 1): link to EBR i + 1 (type 05)
        cbw
        dec ax
        cmp si, ax
        jae .x
        mov al, [cs:hy_n]
        mov cx, si
        inc cx
        mul cl                      ; AX = (i + 1) * n
        mov byte [es:0x1D0], 1
        mov [es:0x1D1], al
        mov word [es:0x1D2], 0xFE05
        mov byte [es:0x1D4], 0x3F
        add al, [cs:hy_n]
        dec ax
        mov [es:0x1D5], al
        mov ax, [bp-2]              ; relative start E_{i+1} - 63 = base_i + stride - 63
        mov dx, [bp-4]
        add ax, [cs:hy_stride]
        adc dx, [cs:hy_stride+2]
        sub ax, 63
        sbb dx, 0
        mov [es:0x1D6], ax
        mov [es:0x1D8], dx
        mov ax, [cs:hy_stride]
        mov dx, [cs:hy_stride+2]
        mov [es:0x1DA], ax
        mov [es:0x1DC], dx
.x:     ret

; Volume boot sector 00h..3Dh (Vailixi D3CB:00F6 mode 1; PMONEY OEM, label, serial).
hy_bpb:     db 0xEB, 0x3C, 0x90, "PMONEY  "     ; 00h jump, OEM name
            dw 512                              ; 0Bh bytes/sector
            db 16                               ; 0Dh sectors/cluster (set per option)
            dw 1                                ; 0Eh reserved sectors
            db 2                                ; 10h FATs
            dw 512                              ; 11h root entries
            dw 0                                ; 13h total sectors (set)
            db 0xF8                             ; 15h media
            dw 11                               ; 16h sectors/FAT (3,752 clusters at most)
            dw 16, 16                           ; 18h sectors/track, heads (BIOS FS: 1..20, 1..32)
            dd 0                                ; 1Ch hidden sectors (set)
            dd 0                                ; 20h total32
            db 0x82, 0, 0x29                    ; 24h drive, reserved, extended signature
            db 0, 0, 0x4D, 0x50                 ; 27h serial "PM" 00 nn (byte 0 set)
            db "PMONEY-PT-?"                    ; 2Bh volume label (letter set)
            db "FAT12   "                       ; 36h
hy_bpb_end:
hy_mb:      dw 8, 16, 24, 31, 32                ; MB per volume shown, options 1..5
hy_n        equ cave_pool               ; hyb_ui .. hyb_write, in the session pool
hy_cnt      equ cave_pool + 1
hy_letter   equ cave_pool + 2
hy_stride   equ cave_pool + 4
hy_ext      equ cave_pool + 8

pm_s_text:  db "Choose the partition layout:", 10, 10
            db "MPC only: stock MPC partitions.", 10
            db "MPC + PC: MPC partitions that a", 10
            db "computer can also read (up to 32 MB).", 0
pm_s_keys:  db "<MPC only> <MPC + PC>", 0
hy_s_title: db "PC-Readable Partitions", 0
hy_s_row:   db "%d. %2d volume(s) of %2d MB", 0
hy_s_ask:   db "SCSI unit %d: %d volume(s) of %d MB.", 0
hy_s_lost:  db "All data on this disk is lost. No undo.", 0
hy_s_keys:  db "<Partition now>", 0
hy_s_busy:  db "Partitioning the drive...", 0

; ======================================================================= H6 mount

; JMPF from the partition reader 2AB2:059D (image 0x2B0BD) in place of PUSH 61h /
; PUSH 0D05h; reached when LBA 0 is not an MPC disk.  Frame of 2AB2:04F7: BP,
; [bp-100Eh] 4 KB buffer = LBA 0, SI and DI pushed, DS = DGROUP.  Clobbers AX, BX,
; CX, DX, ES (the stock path reloads ES).
; Hybrid (D4 MBR, then Vailixi's EBR test on LBA 63, read to buffer + 800h so LBA 0
; stays for the Akai tests): table as 2AB2:054D, AX = 0, the stock success tail.
mnt_hybrid:
        cmp word [SCSI_BLKSIZE], 512
        jne .stock
        push ss
        pop es
        lea bx, [bp-0x100E]
        call du_mbr
        jne .stock
        push ss
        lea ax, [bp-0x100E+0x800]
        push ax
        push byte 1
        push byte 0
        push byte 63
        push word [SCSI_ACTIVE]
        FCALL T_D470_02B5
        add sp, 12
        or ax, ax
        jnz .stock
        push ss
        pop es
        lea bx, [bp-0x100E+0x800]
        call du_sig
        jne .stock
        cmp byte [es:bx+0x18], 0x10
        jne .stock
        cmp byte [es:bx+0x1A], 0x10
        jne .stock
        mov byte [DISK_LAYOUT], 1
        lea si, [bx+0x80]
        mov di, PART_TABLE
        xor cx, cx
.t:     mov ax, [ss:si]             ; entry 0 always, then up to the first zero, 26 at most
        mov dx, [ss:si+2]
        mov [di], ax
        mov [di+2], dx
        jcxz .n
        or ax, dx
        jz .e
.n:     add si, 4
        add di, 4
        inc cx
        cmp cx, 26
        jb .t
.e:     mov [PART_COUNT], cl
        mov al, [ss:bx+0x18]
        mov [PART_SPT], al
        mov al, [ss:bx+0x1A]
        mov [PART_HEADS], al
        xor ax, ax
        pop di
        pop si
        leave
        retf
.stock: push byte 0x61
        push 0x0D05
        FJMP T_D470_075E
