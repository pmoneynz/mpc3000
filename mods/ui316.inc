; Text-page helpers shared by the PROFILE_316 modules (were du_* in diskutil316.inc).
; Register facts, 3.16 image (PROVEN, code): T_B1B1_0026 = 0427:0030 (image 0x42A0)
; reads the byte at [bp+6] (row) into BH and [bp+8] (column) into BL, INT 43 AX=3;
; T_B1B1_005B = 0427:0065 (image 0x42D5) saves and restores DS and DI; 3.16's INT 43
; handler 0009:16A6 (image 0x1736) saves BX, CX, DX, SI, DI, BP, DS, ES.  So both
; wrappers change AX, BX and flags only.

; AL = row: cursor (row, 0).  du_rc: AL = row, AH = column.
; Changes AX and flags only.
du_at:  mov ah, 0
du_rc:  push bx
        mov bl, ah
        push bx                     ; column: the low byte is read
        push ax                     ; row
        FCALL T_B1B1_0026
        add sp, 4
        pop bx
        ret

; AL = row, BX = cave string: cursor (row, 0), then the string.  Changes AX, flags.
du_row_put:
        call du_at
; BX = cave string: print it at the cursor.  Changes AX and flags only.
du_put: push bx
        push cs                     ; cave code runs only at its home: CS = CAVE_SEG
du_put_seg:
        push bx
        FCALL T_B1B1_005B
        add sp, 4
        pop bx
        ret
; BX = DGROUP string: the same.
du_put_ds:
        push bx
        push ds
        jmp du_put_seg

; BX = cave title: new page (field list reset, clear, "== title ==").  Keeps BX, SI, DI.
du_title:
        push bx
        push cs
        push bx
        FCALL T_B509_2289
        add sp, 4
        pop bx
        ret

; BX = soft-key text: '=' rule on row 6, the text on row 7, blanks to column 40.
du_keys:
        push bx
        FCALL T_B77C_20C5
        pop bx
        call du_put
        ; fall through
; Blanks from the cursor to column 40.
du_eol: push byte 40
        FCALL T_B1FF_000C
        add sp, 2
        ret

; AX = soft keys accepted.  Out: AX = the key (never 0), ZF = 1 for Soft Key 1.
du_key: push si
        mov si, ax
.k:     push si
        FCALL T_B060_035D
        add sp, 2
        or ax, ax
        jz .k
        pop si
        cmp ax, 0x78
        ret

; Confirmation: BX = soft-key text.  Queued soft keys are dropped first; only Soft
; Key 1 confirms.  Out: AX = 0 and ZF = 1 confirmed, else AX = the key (ZF = 0).
du_ask: push bx
        FCALL T_D6E0_008B
        pop bx
        call du_keys
        mov ax, 1
        call du_key
        jne .r
        xor ax, ax
.r:     ret

; AX = SCSI code: the stock error box for it.
du_box: push ax
        FCALL T_D510_008D
        push ax
        FCALL T_B3C7_0007
        add sp, 4
        ret

; AX = OS error number: the stock box.
du_err: push ax
        FCALL T_B3C7_0007
        add sp, 2
        ret

; INT 41 AX=0, as before the stock destructive operations (and at the start of a scan).
du_reset:
        push byte 0
        FCALL T_CF0C_0006
        add sp, 2
        ret

; AX = Sound record index 0..127: ES:BX = its record (SND_SEG:SND_DIR + 24h * AX).
; Changes AX, DX, flags.
snd_record:
        mov dx, 0x24
        mul dx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        ret
