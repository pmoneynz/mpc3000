; Save a Sound to an Akai S1000 floppy: Disk -> 8 (Akai S1000/3000), Soft Key 3 <Save>.
; The disk format and the stock Disk 8 loader are notes/akai_disk.md; this
; mod's hooks and evidence are notes/akai_save.md. tools/snd2akai.py writes
; the same files from a PC, and the tests compare the two.
;
; Hooks: mods/AKAI.args.
;   BE7E:130C  Soft Key 3 on the Akai screen (floppy: stock no-op) -> akai_sk3
;   E7F5:0181  FDC command byte, stock READ C6 -> fdc_op ([cs:op_byte])
;   E7F5:0234  DMA mode for the FDC channel, stock 44 -> fdc_dma ([cs:dma_mode])
; With op_byte/dma_mode at their stock values the driver behaves as before;
; only akai_write sets C5/48 (MT|MFM|WRITE, memory -> device), as the BIOS
; does for its own floppy writes (F800:1ED6).
;
; DS = 8010 (DGROUP) in the hooked routines and throughout.
; C convention inside: preserve SI, DI, BP, DS.
; cpu 186: the stock OS uses PUSH imm.

bits 16
cpu 186
org 0

%include "profile.inc"
%ifdef PROFILE_316
 %fatal "akai.asm: generic Vailixi 3.50 only (DGROUP and E7F5 offsets differ)"
%endif
%ifdef WAVE_CAPTURE_20261001
 %fatal "akai.asm: generic Vailixi 3.50 only (DGROUP and E7F5 offsets differ)"
%endif

%define T_BE7E_1313 0xBE7E:0x1313       ; Soft Key 3 on SCSI: Select Volume
%define T_BE7E_133A 0xBE7E:0x133A       ; key loop tail: SI = 0 repaints / loops
%define T_B509_2289 0xB509:0x2289       ; paint a screen title (far string)
%define T_E7F5_0324 0xE7F5:0x0324       ; floppy session: hook IRQ3
%define T_E7F5_0350 0xE7F5:0x0350       ; unhook IRQ3, motor off
%define T_E7F5_0380 0xE7F5:0x0380       ; Akai detect: 2 HD, 1 DD, < 1 error
%define T_E7F5_03E5 0xE7F5:0x03E5       ; block transfer (buf far, bytes dword, block)
%define T_E7F5_0419 0xE7F5:0x0419       ; drive status: non-zero = not ready

DISK_SCSI  equ 0x7CAF           ; non-zero: the Akai screen is on SCSI
FDC_CMD    equ 0x7910           ; command byte of the E7F5 command block DS:790F
FDC_ST1    equ 0x792A           ; result ST1 (ST0 at 7929)
BUF_SEG    equ 0xA2AE           ; stock transfer buffer A2AE:0000-47FF (DS:3F44)
HDR        equ 0x0000           ; disk header: 5 (HD) or 4 (DD) blocks
STAGE      equ 0x1400           ; file blocks on their way to the disk
STAGE_BLKS equ 13               ; 0x1400 + 13 KiB = 0x4800, the sound records

REC_NAME   equ 0x00
REC_TUNE   equ 0x12
REC_STEREO equ 0x13
REC_START  equ 0x14
REC_END    equ 0x18
REC_LEN    equ 0x1C
REC_WAVE   equ 0x20
REC_SIZE   equ 0x24

SHDR       equ 150              ; S1000 sample header; 3.50 reads 0x96 on floppy
FAT        equ 0x600
FAT_SYS    equ 0x4000
FAT_END    equ 0xC000
ENTRIES    equ 64
TYPE_S1000 equ 0x73
OSVER      equ 0x0428

E_NOROOM   equ 0xF900
E_EXISTS   equ 0xF800
E_MAXFILES equ 0xFA00
E_WPROT    equ 0xFF03
E_NOFLOPPY equ 0xFF80
E_NOTAKAI  equ 0xFF49
E_DISK     equ 0xF500

; ---------------------------------------------------------------- FDC hooks

; Replaces `mov byte [7910],C6` (E7F5:0181).
fdc_op:
        push ax
        mov al, [cs:op_byte]
        mov [FDC_CMD], al
        pop ax
        retf

; Replaces `mov dx,C00A / mov al,44 / out dx,al` (E7F5:0234).
fdc_dma:
        mov dx, 0xC00A
        mov al, [cs:dma_mode]
        out dx, al
        retf

; ---------------------------------------------------------------- Soft Key 3

; Replaces `cmp byte [7CAF],0 / jz 1325` at BE7E:130C, inside BE7E:0F9F's
; frame: [bp-0A] stereo prompt state (-1 none), [bp-0C] list position,
; [bp-0E] re-read flag; DI holds the list count.
akai_sk3:
        cmp byte [DISK_SCSI], 0
        je .floppy
        FJMP T_BE7E_1313
.floppy:
        cmp word [bp-0x0A], -1
        jne .inert                      ; stereo prompt open: Soft Key 3 stays inert
        push bp
        push di
        call save_ui
        pop di
        pop bp
        mov word [bp-0x0E], 1           ; re-read the directory, as after a load
        mov word [bp-0x0C], 0
.inert: xor si, si
        FJMP T_BE7E_133A

; ---------------------------------------------------------------- choose a Sound

save_ui:
        mov word [cs:index], -1
        call next_sound
        jnc .paint
        mov si, msg_no_sounds
        jmp msg_wait
.paint: call paint
.key:   push 0
        FCALL T_BDE3_000E
        add sp, 2
        cmp al, 'z'                     ; Soft Key 3
        je .save
        cmp al, 'u'                     ; Soft Key 4
        je .done
        cmp al, '+'
        je .next
        cmp al, '-'
        jne .key
        mov cx, [KEY_REPEAT]
        or cx, cx
        jnz .back
        inc cx
.back:  push cx
        call prev_sound
        pop cx
        loop .back
        jmp .paint
.next:  mov cx, [KEY_REPEAT]
        or cx, cx
        jnz .fwd
        inc cx
.fwd:   push cx
        call next_sound
        pop cx
        loop .fwd
        jmp .paint
.save:  jmp save
.done:  ret

; [cs:index] -> the next used record (wrapping), CF if there is none.
next_sound:
        mov cx, 128
        mov ax, [cs:index]
.try:   inc ax
        and ax, 127
        call used
        jnz .found
        loop .try
        stc
        ret
.found: mov [cs:index], ax
        clc
        ret

prev_sound:
        mov cx, 128
        mov ax, [cs:index]
.try:   dec ax
        and ax, 127
        call used
        jnz .found
        loop .try
        ret
.found: mov [cs:index], ax
        ret

; ZF clear if record AX holds a Sound; preserves AX, CX.
used:
        push ax
        call record
        cmp byte [es:bx], 0
        pop ax
        ret

; ES:BX = record AX.
record:
        mov bx, REC_SIZE
        mul bx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        mov es, ax
        ret

paint:
        call load_sound
        push cs
        push strict word title
        FCALL T_B509_2289
        add sp, 4
        mov ax, 1
.clear: push ax
        xor dx, dx
        call cursor_to
        mov si, blank
        call puts
        pop ax
        inc ax
        cmp ax, 8
        jb .clear
        mov ax, 1
        xor dx, dx
        call cursor_to
        mov si, lbl_sound
        call puts
        mov si, mpc_name
        call puts
        cmp byte [cs:planes], 2
        jne .akai
        mov si, lbl_stereo
        call puts
.akai:  mov ax, 2
        xor dx, dx
        call cursor_to
        mov si, lbl_akai
        call puts
        mov si, name_txt
        call puts
        cmp byte [cs:planes], 2
        jne .size
        mov si, lbl_and
        call puts
        mov si, name_txt + 13
        call puts
.size:  mov ax, 3
        xor dx, dx
        call cursor_to
        mov si, lbl_size
        call puts
        call total_blocks
        call putu
        mov si, lbl_k
        call puts
        mov ax, 5
        xor dx, dx
        call cursor_to
        mov si, msg_wheel
        call puts
        mov ax, 7
        xor dx, dx
        call cursor_to
        mov si, keys
        jmp puts

; ---------------------------------------------------------------- the Sound

; Copy record [cs:index] and derive the Akai names, header fields and size.
load_sound:
        mov ax, [cs:index]
        call record
        push ds
        push es
        pop ds
        mov si, bx
        push cs
        pop es
        mov di, mpc_name
        mov cx, 16
        rep movsb
        mov byte [es:di], 0
        mov al, [bx + REC_TUNE]
        mov [cs:tune], al
        mov al, [bx + REC_STEREO]
        and al, 1
        inc al
        mov [cs:planes], al
        lea si, [bx + REC_START]
        mov di, start
        movsw
        movsw
        lea si, [bx + REC_END]
        mov di, finish
        movsw
        movsw
        lea si, [bx + REC_LEN]
        mov di, len
        movsw
        movsw
        lea si, [bx + REC_WAVE]
        mov di, wave
        movsw
        movsw
        pop ds
        ; Markers 3.50 playback accepts are 0 <= start < end <= len; else the whole sound.
        mov ax, [cs:finish]
        mov dx, [cs:finish + 2]
        cmp dx, [cs:len + 2]
        ja .whole
        jb .end_ok
        cmp ax, [cs:len]
        ja .whole
.end_ok:cmp dx, [cs:start + 2]
        ja .marks
        jb .whole
        cmp ax, [cs:start]
        ja .marks
.whole: xor ax, ax
        mov [cs:start], ax
        mov [cs:start + 2], ax
        mov ax, [cs:len]
        mov [cs:finish], ax
        mov ax, [cs:len + 2]
        mov [cs:finish + 2], ax
.marks: ; File bytes 150 + 2*len; blocks rounded up.
        mov ax, [cs:len]
        mov dx, [cs:len + 2]
        shl ax, 1
        rcl dx, 1
        add ax, SHDR
        adc dx, 0
        mov [cs:file_bytes], ax
        mov [cs:file_bytes + 2], dx
        add ax, 1023
        adc dx, 0
        mov cx, 10
.shift: shr dx, 1
        rcr ax, 1
        loop .shift
        mov [cs:file_blocks], ax
        jmp make_names

; mpc_name -> name_txt (two 13-byte ASCII strings) and name_code (two 12-byte
; Akai names), as tools/snd2akai.py clean_name / sample_names.
make_names:
        push ds
        push cs
        pop ds
        push cs
        pop es
        call .body
        pop ds
        ret
.body:  mov si, mpc_name
        mov di, clean
        xor bx, bx                      ; characters kept
.char:  cmp bx, 16
        je .trim
        mov al, [cs:si]
        inc si
        or al, al
        jz .trim
        cmp al, 'a'
        jb .up
        cmp al, 'z'
        ja .up
        sub al, 'a' - 'A'
.up:    cmp al, '_'
        jne .valid
        mov al, ' '
.valid: push ax
        call code_of                    ; validity only: keep the ASCII
        pop ax
        jnc .keep
        mov al, '-'
.keep:  mov [cs:di + bx], al
        inc bx
        jmp .char
.trim:  ; Drop trailing, then leading, spaces.
        or bx, bx
        jz .empty
        cmp byte [cs:di + bx - 1], ' '
        jne .lead
        dec bx
        jmp .trim
.lead:  cmp byte [cs:di], ' '
        jne .made
        push cx
        mov si, clean + 1
        mov di, clean
        mov cx, 15
        rep movsb
        pop cx
        mov di, clean
        dec bx
        jmp .lead
.empty: mov si, default_name
        mov di, clean
        mov cx, 6
        rep movsb
        mov bx, 6
.made:  mov [cs:clean_len], bx
        cmp byte [cs:planes], 2
        je .stereo
        ; Mono: first 12, trailing spaces dropped; NAME-L/-R becomes NAME L/R.
        cmp bx, 12
        jbe .m12
        mov bx, 12
.m12:   cmp byte [cs:clean + bx - 1], ' '
        jne .mtail
        dec bx
        jmp .m12
.mtail: mov si, clean
        mov di, name_txt
        mov cx, bx
        rep movsb
        mov byte [cs:di], 0
        cmp bx, 2
        jbe .encode
        cmp byte [cs:di - 2], '-'
        jne .encode
        mov al, [cs:di - 1]
        cmp al, 'L'
        je .unpair
        cmp al, 'R'
        jne .encode
.unpair:mov byte [cs:di - 2], ' '
        jmp .encode
.stereo:; Stereo: first 10, trailing spaces dropped, padded to 10, then -L / -R.
        cmp bx, 10
        jbe .s10
        mov bx, 10
.s10:   cmp byte [cs:clean + bx - 1], ' '
        jne .stail
        dec bx
        jmp .s10
.stail: mov di, name_txt
        call .half
        mov word [cs:di], 'L' * 256 + '-'
        mov byte [cs:di + 2], 0
        mov di, name_txt + 13
        call .half
        mov word [cs:di], 'R' * 256 + '-'
        mov byte [cs:di + 2], 0
.encode:mov si, name_txt
        mov di, name_code
        call encode
        mov si, name_txt + 13
        mov di, name_code + 12
        jmp encode
.half:  mov si, clean
        mov cx, bx
        rep movsb
        mov cx, 10
        sub cx, bx
        mov al, ' '
        rep stosb
        ret

; CS:SI ASCII (NUL-ended, <= 12) -> CS:DI 12 Akai codes, space padded.
encode:
        mov cx, 12
.next:  mov al, [cs:si]
        or al, al
        jz .pad
        inc si
        call code_of
        mov [cs:di], al
        inc di
        loop .next
        ret
.pad:   mov al, 10
        rep stosb
        ret

; AL ASCII -> AL Akai code (3.50 table DS:3F1A); CF and AL unchanged if none.
code_of:
        cmp al, '0'
        jb .sym
        cmp al, '9'
        ja .alpha
        sub al, '0'
        clc
        ret
.alpha: cmp al, 'A'
        jb .sym
        cmp al, 'Z'
        ja .sym
        sub al, 'A' - 11
        clc
        ret
.sym:   push di
        push cx
        mov di, symbols
        mov cx, 5
.scan:  cmp al, [cs:di]
        je .hit
        inc di
        loop .scan
        pop cx
        pop di
        stc
        ret
.hit:   mov al, [cs:di + 5]
        pop cx
        pop di
        clc
        ret

; ---------------------------------------------------------------- save

save:
        mov ax, 7
        xor dx, dx
        call cursor_to
        mov si, msg_reading
        call puts
        FCALL T_E7F5_0324
        FCALL T_E7F5_0419
        or ax, ax
        mov ax, E_DISK
        jnz .fail
        FCALL T_E7F5_0380
        mov cx, 1600
        mov dx, 5
        cmp ax, 2
        je .geometry
        mov cx, 800
        mov dx, 4
        cmp ax, 1
        je .geometry
        cmp ax, -2
        mov ax, E_NOTAKAI
        je .fail
        mov ax, E_NOFLOPPY
        jmp .fail
.geometry:
        mov [cs:nblocks], cx
        mov [cs:hblocks], dx
        mov ax, dx
        mov cl, 10
        shl ax, cl
        mov [cs:hbytes], ax
        mov si, HDR
        call akai_read
        mov ax, E_DISK
        jc .fail
        mov ax, BUF_SEG
        mov es, ax
        cmp byte [es:HDR + 0x10], 0xFF
        jne .s1000
        FCALL T_E7F5_0350
        mov si, msg_s3000
        jmp msg_wait
.s1000: ; Room: free FAT blocks and free directory entries.
        xor ax, ax                      ; free blocks
        mov bx, FAT
        mov cx, [cs:nblocks]
.count: cmp word [es:bx], 0
        jne .used
        inc ax
.used:  add bx, 2
        loop .count
        mov dx, ax
        call total_blocks
        cmp ax, dx
        mov ax, E_NOROOM
        ja .fail
        cmp word [cs:file_bytes + 2], 0x100
        jae .fail                       ; the 24-bit size field
        ; Entries: same name refused, enough free.
        xor dx, dx                      ; free entries
        mov bx, HDR
        mov cx, ENTRIES
.entry: cmp byte [es:bx + 16], 0
        jne .named
        inc dx
        jmp .after
.named: mov si, name_code
        call same_name
        mov ax, E_EXISTS
        je .fail
        cmp byte [cs:planes], 2
        jne .after
        mov si, name_code + 12
        call same_name
        je .fail
.after: add bx, 24
        loop .entry
        mov al, [cs:planes]
        xor ah, ah
        cmp dx, ax
        mov ax, E_MAXFILES
        jb .fail
        ; Write.
        push 1
        FCALL T_D980_000C               ; mute, as the stock SND save (E905:0012)
        add sp, 2
        mov word [cs:cursor], 0
        mov byte [cs:plane], 0
.plane: call write_file
        jc .werr
        inc byte [cs:plane]
        mov al, [cs:plane]
        cmp al, [cs:planes]
        jb .plane
        mov si, HDR                     ; directory and FAT last
        mov cx, [cs:hbytes]
        xor dx, dx
        call akai_write
        jc .werr
        push 0
        FCALL T_D980_000C
        add sp, 2
        FCALL T_E7F5_0350
        ret
.werr:  push 0
        FCALL T_D980_000C
        add sp, 2
        mov ax, E_DISK
        test byte [FDC_ST1], 0x02       ; ST1 NW: not writable
        jz .fail
        mov ax, E_WPROT
.fail:  push ax
        FCALL T_E7F5_0350
        FCALL T_B3C7_0007
        add sp, 2
        ret

; AX = blocks for every plane (at most 2 x 32769: wave RAM is 16 M words).
total_blocks:
        mov ax, [cs:file_blocks]
        cmp byte [cs:planes], 2
        jne .one
        shl ax, 1
        jnc .one
        mov ax, 0xFFFF
.one:   ret

; ZF if the 12 Akai codes at CS:SI equal directory entry ES:BX.
same_name:
        push cx
        push di
        mov di, bx
        mov cx, 12
.cmp:   mov al, [cs:si]
        cmp al, [es:di]
        jne .out
        inc si
        inc di
        loop .cmp
        cmp al, al                      ; all 12 equal: ZF (INC cleared it)
.out:   pop di
        pop cx
        ret

; Write plane [cs:plane] as one file: blocks first-fit from [cs:cursor],
; runs of up to STAGE_BLKS contiguous blocks per transfer; then its FAT chain
; end and directory entry (in the header buffer only). CF on a write error.
write_file:
        call make_header
        xor ax, ax
        mov [cs:offset], ax
        mov [cs:offset + 2], ax
        mov word [cs:first], -1
        mov word [cs:prev], -1
.run:   mov ax, BUF_SEG
        mov es, ax
        ; Next free block at or after the cursor (room was counted).
        mov bx, [cs:cursor]
.seek:  mov si, bx
        shl si, 1
        cmp word [es:FAT + si], 0
        je .start
        inc bx
        jmp .seek
.start: mov [cs:run0], bx
        ; Blocks this file still needs: ceil((bytes - offset) / 1024).
        mov ax, [cs:file_bytes]
        mov dx, [cs:file_bytes + 2]
        sub ax, [cs:offset]
        sbb dx, [cs:offset + 2]
        add ax, 1023
        adc dx, 0
        mov cx, 10
.div:   shr dx, 1
        rcr ax, 1
        loop .div
        mov [cs:need], ax
        ; Extend the run while the next block is free.
        mov cx, 1
.grow:  cmp cx, STAGE_BLKS
        je .claim
        cmp cx, [cs:need]
        je .claim
        mov si, bx
        add si, cx
        cmp si, [cs:nblocks]
        jae .claim
        shl si, 1
        cmp word [es:FAT + si], 0
        jne .claim
        inc cx
        jmp .grow
.claim: mov [cs:runlen], cx
        ; Chain the run: each block to the next, the last to END for now.
        mov si, bx
        shl si, 1
.link:  inc bx
        mov [es:FAT + si], bx
        add si, 2
        loop .link
        mov word [es:FAT + si - 2], FAT_END
        mov [cs:cursor], bx
        mov ax, [cs:run0]
        mov si, [cs:prev]
        cmp si, -1
        jne .join
        mov [cs:first], ax
        jmp .joined
.join:  shl si, 1
        mov [es:FAT + si], ax
.joined:dec bx
        mov [cs:prev], bx
        ; Fill the stage and write it.
        call fill_stage
        mov si, STAGE
        mov cx, [cs:runlen]
        shl cx, 10
        mov dx, [cs:run0]
        call akai_write
        jc .ret
        mov ax, [cs:runlen]
        shl ax, 10
        add [cs:offset], ax
        adc word [cs:offset + 2], 0
        mov ax, [cs:offset]
        mov dx, [cs:offset + 2]
        cmp dx, [cs:file_bytes + 2]
        jb .run
        ja .entry
        cmp ax, [cs:file_bytes]
        jb .run
.entry: ; First free directory entry.
        mov ax, BUF_SEG
        mov es, ax
        mov di, HDR
.free:  cmp byte [es:di + 16], 0
        je .fill
        add di, 24
        jmp .free
.fill:  mov si, name_code
        cmp byte [cs:plane], 0
        je .copy
        add si, 12
.copy:  mov cx, 12
.name:  mov al, [cs:si]
        stosb
        inc si
        loop .name
        mov ax, 0x2020                  ; S1000 tags
        stosw
        stosw
        mov al, TYPE_S1000
        stosb
        mov ax, [cs:file_bytes]
        stosw
        mov al, [cs:file_bytes + 2]
        stosb
        mov ax, [cs:first]
        stosw
        mov ax, OSVER
        stosw
        clc
.ret:   ret

; The 150-byte S1000 header for plane [cs:plane] (tools/snd2akai.py sample_header).
make_header:
        push cs
        pop es
        mov di, shdr
        xor ax, ax
        mov cx, SHDR / 2
        rep stosw
        mov di, shdr
        mov word [cs:di], 0x0103        ; block ID 3, bandwidth 20 kHz
        mov byte [cs:di + 2], 60        ; root key
        mov si, name_code
        cmp byte [cs:plane], 0
        je .name
        add si, 12
.name:  lea di, [di + 3]
        mov cx, 12
        push ds
        push cs
        pop ds
        rep movsb
        pop ds
        mov di, shdr
        mov byte [cs:di + 0x0F], 0x80
        mov byte [cs:di + 0x13], 2      ; play mode: no loop
        ; Tune: round(t * 25.6) = (256 t +- 5) / 10, which 3.50 maps back to t.
        mov al, [cs:tune]
        cbw
        mov cl, 8
        sal ax, cl                      ; |t| <= 127: fits
        mov cx, 5
        or ax, ax
        jns .pos
        neg cx
.pos:   add ax, cx
        cwd
        mov cx, 10
        idiv cx                         ; truncates toward zero
        mov [cs:di + 0x14], ax
        mov ax, [cs:len]
        mov [cs:di + 0x1A], ax
        mov ax, [cs:len + 2]
        mov [cs:di + 0x1C], ax
        mov ax, [cs:start]
        mov [cs:di + 0x1E], ax
        mov ax, [cs:start + 2]
        mov [cs:di + 0x20], ax
        mov ax, [cs:finish]
        mov [cs:di + 0x22], ax
        mov ax, [cs:finish + 2]
        mov [cs:di + 0x24], ax
        mov word [cs:di + 0x88], 0xFFFF ; no stereo partner address
        mov word [cs:di + 0x8A], 44100
        ret

; Stage [runlen] blocks of the file from [offset]: the header (offset 0 only),
; then PCM read from wave RAM (CF92:000C, dir 1), zero after the end.
fill_stage:
        mov ax, BUF_SEG
        mov es, ax
        mov di, STAGE
        mov cx, [cs:runlen]
        shl cx, 9
        xor ax, ax
        rep stosw
        mov di, STAGE                   ; destination of the PCM
        xor ax, ax                      ; PCM byte offset (low word, high in DX)
        xor dx, dx
        mov bx, [cs:runlen]
        shl bx, 10                      ; bytes available in the stage
        mov cx, [cs:offset]
        or cx, [cs:offset + 2]
        jnz .later
        push ds
        push cs
        pop ds
        mov si, shdr
        mov di, STAGE
        mov cx, SHDR
        rep movsb
        pop ds
        sub bx, SHDR
        xor ax, ax
        xor dx, dx
        jmp .pcm
.later: mov ax, [cs:offset]
        mov dx, [cs:offset + 2]
        sub ax, SHDR
        sbb dx, 0
.pcm:   ; AX:DX = PCM byte offset, DI = stage offset, BX = room (bytes).
        mov [cs:pcm_off], ax
        mov [cs:pcm_off + 2], dx
        ; Bytes left: 2*len - pcm_off.
        mov ax, [cs:len]
        mov dx, [cs:len + 2]
        shl ax, 1
        rcl dx, 1
        sub ax, [cs:pcm_off]
        sbb dx, [cs:pcm_off + 2]
        or dx, dx
        jnz .full
        cmp ax, bx
        jbe .count
.full:  mov ax, bx
.count: shr ax, 1                       ; words
        jz .ret
        mov [cs:words], ax
        ; Wave word address: wave + plane*len + pcm_off/2.
        mov ax, [cs:pcm_off]
        mov dx, [cs:pcm_off + 2]
        shr dx, 1
        rcr ax, 1
        add ax, [cs:wave]
        adc dx, [cs:wave + 2]
        cmp byte [cs:plane], 0
        je .addr
        add ax, [cs:len]
        adc dx, [cs:len + 2]
.addr:  inc byte [BUSY]
        push 1                          ; wave RAM -> memory
        push 0
        push word [cs:words]
        push dx
        push ax
        push strict word BUF_SEG
        push di
        FCALL T_CF92_000C
        add sp, 14
        dec byte [BUSY]
.ret:   ret

; Read [hbytes] bytes from block 0 into BUF_SEG:SI. CF on error.
akai_read:
        push 0
        push 0
        push word [cs:hbytes]
        push strict word BUF_SEG
        push si
        FCALL T_E7F5_03E5
        add sp, 10
        or ax, ax
        jz .ok
        stc
.ok:    ret

; Write CX bytes from BUF_SEG:SI to block DX. CF on error.
akai_write:
        mov byte [cs:op_byte], 0xC5     ; MT|MFM|WRITE DATA
        mov byte [cs:dma_mode], 0x48    ; memory -> device
        push dx
        push 0
        push cx
        push strict word BUF_SEG
        push si
        FCALL T_E7F5_03E5
        add sp, 10
        mov byte [cs:op_byte], 0xC6
        mov byte [cs:dma_mode], 0x44
        or ax, ax
        jz .ok
        stc
.ok:    ret

; ---------------------------------------------------------------- text

; Cursor to row AX, column DX.
cursor_to:
        push dx
        push ax
        FCALL T_B1B1_0026
        add sp, 4
        ret

; Put the CS string at SI.
puts:
        push cs
        push si
        FCALL T_B1B1_005B
        add sp, 4
        ret

; Put AX in decimal.
putu:
        mov si, number + 5
        mov byte [cs:si], 0
        mov cx, 10
.digit: xor dx, dx
        div cx
        add dl, '0'
        dec si
        mov [cs:si], dl
        or ax, ax
        jnz .digit
        jmp puts

; Show CS:SI on the bottom line until a key.
msg_wait:
        push si
        mov ax, 7
        xor dx, dx
        call cursor_to
        mov si, blank
        call puts
        mov ax, 7
        xor dx, dx
        call cursor_to
        pop si
        call puts
        push 0
        FCALL T_BDE3_000E
        add sp, 2
        ret

; ---------------------------------------------------------------- data

title         db "Save Sound to Akai S1000 Disk", 0
lbl_sound     db "Sound:", 0
lbl_stereo    db "  (stereo)", 0
lbl_akai      db "Akai: ", 0
lbl_and       db " and ", 0
lbl_size      db "Size:", 0
lbl_k         db "K", 0
msg_wheel     db "Choose with the data wheel.", 0
keys          db "                    <Save it> <Cancel>", 0
msg_reading   db "Saving to disk...                       ", 0
msg_no_sounds db "No sounds to save.  Press a key.", 0
msg_s3000     db "S3000 disk: use an S1000 disk.", 0
default_name  db "SAMPLE"
blank         times 40 db ' '
              db 0
symbols       db ' #+-.', 10, 37, 38, 39, 40

op_byte    db 0xC6
dma_mode   db 0x44
planes     db 0
plane      db 0
tune       db 0
index      dw 0
nblocks    dw 0
hblocks    dw 0
hbytes     dw 0
file_blocks dw 0
cursor     dw 0
first      dw 0
prev       dw 0
run0       dw 0
runlen     dw 0
need       dw 0
words      dw 0
clean_len  dw 0
start      dd 0
finish     dd 0
len        dd 0
wave       dd 0
file_bytes dd 0
offset     dd 0
pcm_off    dd 0
number     times 6 db 0
mpc_name   times 17 db 0
clean      times 16 db 0
name_txt   times 26 db 0
name_code  times 24 db 0
shdr       times SHDR db 0
