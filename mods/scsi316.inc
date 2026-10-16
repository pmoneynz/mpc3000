; Vailixi 3.50 F12/F13 on OS 3.16 (PMONEY cave, PROFILE_316 only): multi-sector
; SCSI transfers on/off and an SPC reset after each failed AUTO-search probe,
; as two rows on Disk 9 4 SCSI Status.  Screen text is PMONEY's own.
; Hooks (WAVE316.args form):
;   --patch=2ac3b:f6066cf101747a:ea{scsi_rw_mode}9090
;   --patch=2af31:803e0f8300:9a{scsi_scan_reset}
;   --patch=8f05:1e680a2c9a6500270483c404:9a{scsi_page_rows}90909090909090
;
; Settings in the parameter-block reserve (stock zero-fill = Vailixi defaults):
;   SCSI_MULTI_OFF [831B] (Vailixi [862D], default ON = 1): stored inverted, 0 = ON.
;   SCSI_AUTO_RESET [831C] (Vailixi [862E], default OFF = 0): stored direct.

; JMPF from 2AB2:011B (image 0x2AC3B; Vailixi D470:0115..0120 + D470:01CE),
; replacing TEST BYTE [F16C],1 / JZ 019C (7 bytes; 2 NOPs follow).
; In: the frame of 2AB2:00FF (sector read/write, CALLF):  BP frame, [bp-2] word
; local, SI = count (512-byte sectors), DI = SCSI ID, [bp+8] LBA dword, [bp+0Eh]
; buffer far, [bp+12h] SCSI opcode (08h read, 0Ah write); CDB[0] and CDB[5] set.
; DS = DGROUP.  Out: ON (stock): jumps back into 2AB2.  OFF: one READ(6)/WRITE(6)
; per device block, returns through 2AB2:01FC with DX = 0 or the first error.
scsi_rw_mode:
        cmp byte [SCSI_MULTI_OFF], 0
        jne .single
        test byte [SCSI_SYQUEST], 1     ; the replaced test
        jnz .stock_single
        FJMP T_D470_024F                ; 2AB2:019C multi-sector command
.stock_single:
        FJMP T_D470_0249                ; 2AB2:0196 stock one-block loop (SyQuest SQ52)
.single:                                ; Vailixi D470:0121..01B3
        mov ax, 1
        cmp byte [SCSI_DEVTYPE], 5      ; 2048-byte blocks: 4 sectors per block
        jne .step
        mov ax, 4
.step:  mov [bp-2], ax
        xor dx, dx                      ; deviation: defined result for count 0
        jmp .test
.loop:  mov al, [bp+0x12]
        mov [SCSI_CDB], al
        mov al, [bp+0x0A]
        and al, 0x1F
        mov [SCSI_CDB+1], al
        mov al, [bp+0x09]
        mov [SCSI_CDB+2], al
        mov al, [bp+0x08]
        mov [SCSI_CDB+3], al
        mov byte [SCSI_CDB+4], 1
        mov byte [SCSI_CDB+5], 0
        push word [SCSI_BLKSIZE]        ; length: one device block
        push word [bp+0x10]
        push word [bp+0x0E]
        push byte 6
        push ds
        push SCSI_CDB
        push di
        FCALL T_D510_0006               ; 2B36:000A command with retries
        add sp, 14
        mov dx, ax
        or dx, dx
        jnz .done
        add word [bp+0x08], 1
        adc word [bp+0x0A], 0
        cmp si, [bp-2]
        jbe .last
        sub si, [bp-2]
        jmp .next
.last:  xor si, si
.next:  mov ax, [SCSI_BLKSIZE]
        add [bp+0x0E], ax
.test:  or si, si
        jnz .loop
.done:  FJMP T_D470_02AF                ; 2AB2:01FC mov ax,dx / pop di / pop si / leave / retf

; CALLF from the scan 2AB2:0411 (image 0x2AF31; Vailixi D470:04C4..04D0),
; replacing CMP BYTE [830F],0 (5 bytes); the JZ 041E after it tests ZF (RETF keeps it).
; Runs after every ID probe that did not return 0.  Clobbers AX, flags (AX dead there).
scsi_scan_reset:
        cmp byte [SCSI_AUTO_RESET], 0
        je .cmp
        FCALL T_D3A7_0014               ; 2A66:0012 SPC init, as at the scan's start
.cmp:   cmp byte [SCSI_UNIT], 0         ; the replaced instruction
        retf

; CALLF from the SCSI Status page 077D:1735 (image 0x8F05), replacing the row-3
; title print PUSH DS / PUSH 2C0A / CALLF 0427:0065 / ADD SP,4 (12 bytes; 7 NOPs).
; Adds the two choice fields on rows 2 and 3 before the stock unit (row 4) and
; timeout (row 5) fields.  Keeps SI, DI, BP, DS.
scsi_page_rows:
        ; The stock page re-renders after <Make active> without resetting its
        ; field list: rebuild it on every pass, or the rows are added again
        ; and the cursor index lands on a duplicate.
        mov word [FIELD_PTR], FIELD_FIRST
        mov al, 2
        call du_at
        push byte 3
        push cs
        push xp_on_off                  ; inverted list: 0 shows ON
        push ds
        push SCSI_MULTI_OFF
        push cs
        push scsi_s_multi
        FCALL T_B354_01C6
        add sp, 14
        mov al, 3
        call du_at
        push byte 3
        push ds
        push XP_OFF_ON                  ; DS:0030 "OFF", "ON "
        push ds
        push SCSI_AUTO_RESET
        push cs
        push scsi_s_reset
        FCALL T_B354_01C6
        add sp, 14
        retf

scsi_s_multi: db "Multi-sector SCSI transfers:         ", 0
scsi_s_reset: db "Reset SCSI chip on AUTO search:      ", 0
