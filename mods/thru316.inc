; OS 3.16: Input Thru, live input monitoring in every mode (design:
; notes/input_thru.md).  Mixer/Effects -> 6 sets Thru OFF / MONO LFT / MONO RGT
; / STEREO, Input ANALOG / DIGITAL and a level; the settings live in the
; parameter-block reserve (THRU_MODE..THRU_LEVEL), saved like xparams316's.
;
; The engine is the stock Sample New Sound monitor (2F37:0456 input, 2F37:033A
; record, 2F37:0008 monitor; Vailixi D90C:0454 / 0338 / 0006), rebuilt with
; its own rings and without the stock's 32-voice clears:
;   ADC --DMA ch2--> thru_cpu_ring --DMA ch3--> DSP record voice 0 (+16)
;   --> wave ring (top THRU_WAVE_WORDS of wave RAM, out of the pool by
;   WAVE316.args F) --> monitor voice 31 (+3), looping the same range.
; Mono reserves channels 0 and 31, stereo 0, 16, 3 and 31.  Reserved channels
; are skipped by the allocator's free return (thru_alloc_free), the one-channel
; stop (thru_stop_guard, so stop-all too) and never reach its steal pass.
;
; Stages: "input" = 8255 input select (and its settle waits); "stage" = both
; DMA channels restarted together, the record and monitor voices programmed and
; keyed.  Wave transfers, the floppy BIOS (it masks ch2/ch3) and the MIDI
; sample dump's all-voice reg-1 init run with the stage paused; Sample New
; Sound runs with Thru fully off.  Every DSP write sequence runs at task level
; holding AMX resource 1, as the stock voice code does.

THRU_WAVE_WORDS equ 0x2000          ; wave ring, words: WAVE316.args F takes it out of the pool
THRU_MONO_LEN   equ 0x1FF0          ; mono loop, words (end 16-word aligned)
THRU_HALF_LEN   equ 0x0FF0          ; stereo loop per side, words
THRU_HALF_STEP  equ 0x1000          ; right side start - left side start
THRU_CPU_WORDS  equ 0x400           ; DMA ring between ch2 and ch3
THRU_LEVEL_DEF  equ 31              ; shown level when the stored byte is 0 (~ stock 50h)
THRU_QUIET      equ 10              ; 100 Hz ticks without a pause before the stage resumes
THRU_RUN_SEG    equ 0x6900 + CAVE_HOME  ; the cave's CS at run time (entry316 UNIV_SEG)

; ---------------------------------------------------------------- state (cave)

thru_resv:      times 32 db 0       ; 1 = channel reserved by Thru
thru_in_on:     db 0                ; input stage armed
thru_stage_on:  db 0                ; DMA, record and monitor voices running
thru_hold:      db 0                ; nested pauses in progress
thru_cur_mode:  db 0                ; armed stock mode: 0 MONO-LFT, 1 MONO-RGT, 2 STEREO
thru_cur_input: db 0                ; armed input: 0 analog, 1 digital
thru_status:    db 0                ; 0 off, 1 on, 2 no digital lock, 3 no wave RAM
thru_fdc_held:  db 0                ; thru_fdc_enter paused the stage
thru_pending:   db 0                ; the last pause ended; thru_idle resumes the stage
thru_quiet_at:  dw 0                ; [LC_TICKS] when it ended
thru_level_shown: db 0              ; the page's level field (stored XOR THRU_LEVEL_DEF)
thru_mix:       dw 0                ; monitor reg-7 lane 62 bytes: level, 0..FFh
; Wave ring, encoded per side: top (A[24:20]), mid (A[19:4]), low (A[3:0]<<12),
; end high ((E>>20)|110h), end low (E[19:4]).  Side 0 is mono / left.
thru_wave:      times 10 dw 0
thru_dma_lo:    dw 0                ; CPU ring physical address bits 15..0
thru_dma_hi:    db 0                ; and 23..16

; ---------------------------------------------------------------- port helpers

; DMA mask register read-modify-write as 2F37:055B / 0576 (Vailixi D90C:0559 /
; 0574): CL = bits to set (thru_dma_mask) or the AND mask (thru_dma_unmask).
thru_dma_mask:
        push bx
        push dx
        mov dx, 0xC008
        mov bx, 0xC00F
        mov ax, 0x14
        pushf
        cli
        out dx, ax
        xchg bx, dx
        in al, dx
        or al, cl
        jmp thru_dma_mask_tail
thru_dma_unmask:
        push bx
        push dx
        mov dx, 0xC008
        mov bx, 0xC00F
        mov ax, 0x14
        pushf
        cli
        out dx, ax
        xchg bx, dx
        in al, dx
        and al, cl
thru_dma_mask_tail:
        out dx, al
        xchg dx, bx
        mov ax, 0x10
        out dx, ax
        popf
        pop dx
        pop bx
        ret

; AL = channel, AH = mode: program it on thru_cpu_ring (autoinit, as the stock
; ch2 55h / ch3 59h).  IF must be clear; changes AX, DX.
thru_dma_prog:
        mov dx, 0xC001
        out dx, al
        mov al, ah
        push ax
        mov ax, [cs:thru_dma_lo]
        mov dx, 0xC004
        out dx, ax
        mov al, [cs:thru_dma_hi]
        mov dx, 0xC006
        out dx, al
        mov ax, THRU_CPU_WORDS - 1
        mov dx, 0xC002
        out dx, ax
        pop ax
        mov dx, 0xC00A
        out dx, al
        ret

; AX = 100 Hz ticks: busy-wait as 2F37:0443 (needs IF = 1).  Changes flags.
thru_wait:
        push bx
        push dx
        mov bx, [LC_TICKS]
.w:     mov dx, [LC_TICKS]
        sub dx, bx
        cmp dx, ax
        jng .w
        pop dx
        pop bx
        ret

; Port 68h busy bit (7) clear, bounded.  Changes AX, CX.
thru_dsp_idle:
        mov cx, 0xFFFF
.w:     in al, 0x68
        test al, 0x80
        loopnz .w
        ret

; ---------------------------------------------------------------- voices

; Program channel BL from wave side SI (0 or 10): start, end, loop (regs 0, 1,
; 2), as 2F37:033A / 0008.  Changes AX.
thru_voice_ring:
        mov ah, 0
        mov al, bl
        out 0x60, ax                    ; reg 0: start
        mov ax, [cs:thru_wave+si]
        or ax, 0x100
        out 0x66, ax
        mov ax, [cs:thru_wave+si+2]
        out 0x64, ax
        mov ax, [cs:thru_wave+si+4]
        out 0x62, ax
        mov ah, 1
        mov al, bl
        out 0x60, ax                    ; reg 1: end, step 1000h
        mov ax, [cs:thru_wave+si+6]
        out 0x66, ax
        mov ax, [cs:thru_wave+si+8]
        out 0x64, ax
        mov ax, 0x1000
        out 0x62, ax
        mov ah, 2
        mov al, bl
        out 0x60, ax                    ; reg 2: loop = start
        mov ax, [cs:thru_wave+si+2]
        out 0x64, ax
        mov ax, [cs:thru_wave+si+4]
        or ax, [cs:thru_wave+si]
        out 0x62, ax
        ret

; Record channel BL on side SI: the ring, mixer zeroed (port 6Ch).  Changes AX.
thru_voice_rec:
        call thru_voice_ring
        mov ah, 7
        mov al, bl
        out 0x60, ax
        xor ax, ax
        out 0x6C, ax
        ret

; Monitor channel BL on side SI, mixer lane 62 = DX: the ring and the stock
; monitor envelope (2F37:0008), then key it on.  Changes AX, CX.
thru_voice_mon:
        call thru_voice_ring
        mov ah, 4
        mov al, bl
        out 0x60, ax                    ; reg 4: volume target
        mov ax, 0xFFFF
        out 0x64, ax
        mov ax, 0x02E1
        out 0x62, ax
        mov ah, 6
        mov al, bl
        out 0x60, ax                    ; reg 6: filter target
        mov ax, 0x7FF0
        out 0x64, ax
        mov ax, 0x0147
        out 0x62, ax
        mov ah, 5
        mov al, bl
        out 0x60, ax                    ; reg 5: filter
        mov ax, 0x3FFF
        out 0x64, ax
        mov ax, 0xFFFF
        out 0x62, ax
        mov ah, 3
        mov al, bl
        out 0x60, ax                    ; reg 3: volume envelope
        xor ax, ax
        out 0x64, ax
        out 0x62, ax
        call thru_voice_mix
        in al, 0x68                     ; key on the selected channel (2325:00DB)
        mov ah, 1
        and ax, 0xFF7F
        out 0x68, ax
        jmp thru_dsp_idle

; Mixer of channel BL: lane 64 = 0 (no send), lane 62 = DX.  Changes AX.
thru_voice_mix:
        mov ah, 7
        mov al, bl
        out 0x60, ax
        xor ax, ax
        out 0x64, ax
        mov ax, dx
        out 0x62, ax
        ret

; Stock one-channel stop of channel AX past thru_stop_guard (reserves and
; releases AMX resource 1 itself; owner FF, timers 0).  Keeps every register.
thru_raw_stop:
        pusha
        push ax
        push cs
        call .stop
        add sp, 2
        popa
        ret
.stop:  push bp
        mov bp, sp
        mov dx, 1
        FJMP T_D21F_000E

; Stop every reserved channel (outside resource 1).  Keeps every register.
thru_stop_reserved:
        push ax
        push bx
        xor bx, bx
.c:     cmp byte [cs:thru_resv+bx], 0
        je .n
        mov ax, bx
        call thru_raw_stop
.n:     inc bx
        cmp bx, 32
        jb .c
        pop bx
        pop ax
        ret

; ---------------------------------------------------------------- stages

; Stage on: restart ch2 and ch3 together, record and monitor voices, as
; 2F37:033A + 2F37:0008.  Takes AMX resource 1.  Changes AX, BX, CX, DX, SI.
thru_stage_start:
        FCALL T_D1F7_0126
        pushf
        cli
        mov cl, 0x0C                    ; mask ch2, ch3
        call thru_dma_mask
        mov ax, 0x5502
        call thru_dma_prog
        mov ax, 0x5903
        call thru_dma_prog
        mov cl, 0xF3                    ; unmask both
        call thru_dma_unmask
        popf
        xor si, si
        xor bl, bl
        call thru_voice_rec             ; channel 0, mono / left side
        mov al, 0x40
        cmp byte [cs:thru_cur_mode], 2
        jne .ctl
        mov si, 10
        mov bl, 0x10
        call thru_voice_rec             ; channel 16, right side
        mov al, 0x58
.ctl:   xor ah, ah
        out 0x68, ax                    ; record DMA on (40h mono, 58h stereo)
        call thru_dsp_idle
        xor si, si
        mov bl, 0x1F
        mov dl, [cs:thru_mix]
        mov dh, dl                      ; mono: centre
        cmp byte [cs:thru_cur_mode], 2
        jne .mon
        xor dl, dl                      ; stereo: 31 left only
        call thru_voice_mon
        mov si, 10
        mov bl, 3
        xor dh, dh
        mov dl, [cs:thru_mix]           ; 3 right only
.mon:   call thru_voice_mon
        FCALL T_D1F7_012F
        mov byte [cs:thru_stage_on], 1
        ret

; Stage off: record DMA and both channels stopped, monitor voices stopped.
; Changes AX, CX.
thru_stage_stop:
        cmp byte [cs:thru_stage_on], 0
        je .r
        mov byte [cs:thru_stage_on], 0
        xor ax, ax
        out 0x68, ax
        mov cl, 0x0C
        call thru_dma_mask
        mov ax, 0x1F
        call thru_raw_stop
        mov ax, 3
        cmp byte [cs:thru_resv+3], 0
        je .r
        call thru_raw_stop
.r:     ret

; Input on for [cs:thru_cur_mode] / [cs:thru_cur_input]: reserve the channels,
; stop them, select the input as 2F37:0456 (without its 32-voice clear).
; Out: CF = 1 when the digital receiver is not locked (nothing left armed).
; Changes AX, BX, CX, DX.
thru_input_start:
        mov al, 1
        mov [cs:thru_resv], al
        mov [cs:thru_resv+31], al
        cmp byte [cs:thru_cur_mode], 2
        jne .resv
        mov [cs:thru_resv+3], al
        mov [cs:thru_resv+16], al
.resv:  mov byte [ALLOC_VICTIM], 1      ; the steal fallback names no reserved channel
        call thru_stop_reserved
        xor ax, ax
        out 0x68, ax
        mov cl, 0x0C
        call thru_dma_mask
        in al, 0xFC
        and al, 0xCF
        out 0xFC, al
        mov bl, [cs:thru_cur_mode]
        cmp byte [cs:thru_cur_input], 0
        jne .digital
        in al, 0xFC                     ; analog (2F37:04ED)
        and al, 0xCF
        or al, 0x80
        out 0xFC, al
        in al, 0xFA
        and al, 0xEF
        out 0xFA, al
        in al, 0xFC
        and al, 0x4F
        out 0xFC, al
        mov al, 0
        out 0x80, al
        mov ax, 10
        call thru_wait
        in al, 0xFA
        and al, 0xEF
        out 0xFA, al
        inc bl                          ; mode 0/1/2 -> 10h/20h/30h
        mov cl, 4
        shl bl, cl
        in al, 0xFC
        or al, bl
        or al, 0x40
        out 0xFC, al
        jmp .ok
.digital:
        in al, 0x80                     ; 2F37:046F
        and al, 0x60
        cmp al, 0x40
        je .locked
        mov al, 0x30
        out 0x80, al
        mov ax, 2
        call thru_wait
        mov al, 0x70
        out 0x80, al
        mov ax, 5
        call thru_wait
        in al, 0x84
        test al, 0x40
        jz .locked
        call thru_input_restore
        stc
        ret
.locked:
        inc bl                          ; mode 0/1/2 -> 2/4/6
        shl bl, 1
        in al, 0x80
        and al, 0xF9
        or al, bl
        out 0x80, al
        and al, 0x9F
        or al, 0x40
        out 0x80, al
.ok:    mov byte [cs:thru_in_on], 1
        clc
        ret

; Input off as 2F37:016E without its voice clears, then the reserved channels
; stopped, their reg 1 reset as 2338:0000 does, and released.  Changes AX, BX,
; CX, DX.
thru_input_stop:
        call thru_stage_stop
        cmp byte [cs:thru_in_on], 0
        je thru_input_done
        mov byte [cs:thru_in_on], 0
thru_input_restore:
        xor ax, ax
        out 0x68, ax
        mov cl, 0x0C
        call thru_dma_mask
        in al, 0xFC
        and al, 0xCF
        or al, 0x80
        out 0xFC, al
        in al, 0x80
        and al, 0xF9
        out 0x80, al
        call thru_stop_reserved
        FCALL T_D1F7_0126
        xor bx, bx
.c:     cmp byte [cs:thru_resv+bx], 0
        je .n
        mov byte [cs:thru_resv+bx], 0
        mov ax, 0x100
        add ax, bx
        out 0x60, ax
        xor ax, ax
        out 0x62, ax
        dec ax
        out 0x64, ax
        mov ax, 0x0F
        out 0x66, ax
.n:     inc bx
        cmp bx, 32
        jb .c
        FCALL T_D1F7_012F
thru_input_done:
        ret

; Wave ring and CPU ring addresses from the bank count (top of wave RAM).
; Out: CF = 1 if there is no wave RAM.  Changes AX, BX, CX, DX, SI.
thru_rings:
        mov ax, cs                      ; CPU ring: physical 300000h + CS*16 + offset
        mov dx, ax
        mov cl, 4
        shl ax, cl
        mov cl, 12
        shr dx, cl
        add ax, thru_cpu_ring
        adc dl, 0x30
        mov [cs:thru_dma_lo], ax
        mov [cs:thru_dma_hi], dl
        mov dx, [POOL_BANKS]            ; wave words: banks << 20
        or dx, dx
        jz .none
        cmp dx, 8
        ja .none
        mov cl, 4
        shl dx, cl
        xor ax, ax
        sub ax, THRU_WAVE_WORDS         ; A = top - ring
        sbb dx, 0
        xor si, si
        mov bx, THRU_MONO_LEN
        cmp byte [cs:thru_cur_mode], 2
        jne .one
        mov bx, THRU_HALF_LEN
        call thru_side
        add ax, THRU_HALF_STEP
        adc dx, 0
        mov si, 10
.one:   call thru_side
        clc
        ret
.none:  stc
        ret

; Side SI: start DX:AX, length BX words.  Keeps AX, DX.  Changes CX.
thru_side:
        push ax
        push dx
        mov cx, dx                      ; top = A[24:20]
        shr cx, 4
        and cx, 0x1F
        mov [cs:thru_wave+si], cx
        mov cx, ax                      ; low = A[3:0] << 12
        shl cx, 12
        mov [cs:thru_wave+si+4], cx
        mov cx, dx                      ; mid = A[19:4]
        shl cx, 12
        shr ax, 4
        or ax, cx
        mov [cs:thru_wave+si+2], ax
        pop dx
        pop ax
        push ax
        push dx
        add ax, bx                      ; end E = A + length: (E>>20)|110h, E[19:4]
        adc dx, 0
        mov cx, dx
        shl cx, 12
        shr ax, 4
        or ax, cx
        mov [cs:thru_wave+si+8], ax
        shr dx, 4
        or dx, 0x110
        mov [cs:thru_wave+si+6], dx
        pop dx
        pop ax
        ret

; ---------------------------------------------------------------- control

; Bring the hardware to the settings (task level, IF = 1).
; Idempotent; a level change alone rewrites the monitor mixers.  Keeps every
; register.
thru_sync:
        pusha
        push ds
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        mov al, [THRU_LEVEL]            ; level byte for reg 7
        xor al, THRU_LEVEL_DEF
        cmp al, 100
        jbe .lvl
        mov al, 100
.lvl:   mov ah, 0
        mov cx, 255
        mul cx
        add ax, 50
        mov cl, 100
        div cl
        mov [cs:thru_mix], al
        mov bl, [THRU_MODE]             ; wanted: BL = stock mode + 1, 0 = off
        cmp bl, 3
        jbe .m
        xor bl, bl
.m:     mov bh, [THRU_INPUT]
        cmp bh, 1
        jbe .i
        xor bh, bh
.i:     cmp byte [cs:thru_in_on], 0
        je .start
        or bl, bl
        jz .off
        mov al, bl
        dec al
        cmp al, [cs:thru_cur_mode]
        jne .off
        cmp bh, [cs:thru_cur_input]
        jne .off
        cmp byte [cs:thru_stage_on], 0
        je .stage
        call thru_level                 ; unchanged routing: the level only
        jmp .done
.off:   push bx
        call thru_input_stop
        pop bx
        mov byte [cs:thru_status], 0
.start: or bl, bl
        jz .done
        dec bl
        mov [cs:thru_cur_mode], bl
        mov [cs:thru_cur_input], bh
        call thru_rings
        mov byte [cs:thru_status], 3
        jc .done
        call thru_input_start
        mov byte [cs:thru_status], 2
        jc .done
        mov byte [cs:thru_status], 1
.stage: cmp byte [cs:thru_hold], 0
        jne .done
        mov byte [cs:thru_pending], 0
        call thru_stage_start
.done:  pop ds
        popa
        ret

; Rewrite the monitor mixers from [cs:thru_mix] under resource 1.
thru_level:
        FCALL T_D1F7_0126
        mov bl, 0x1F
        mov dl, [cs:thru_mix]
        mov dh, dl
        cmp byte [cs:thru_cur_mode], 2
        jne .one
        xor dl, dl
        call thru_voice_mix
        mov bl, 3
        xor dh, dh
        mov dl, [cs:thru_mix]
.one:   call thru_voice_mix
        FCALL T_D1F7_012F
        ret

; Pause the stage around a guarded call.  Keeps every register except AL:
; AL = 1 if this call paused (pass it to thru_resume), else 0.
thru_pause:
        mov al, 0
        cmp byte [cs:thru_in_on], 0
        je .r
        push ds
        push cx
        push ax
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        inc byte [cs:thru_hold]
        call thru_stage_stop
        pop ax
        pop cx
        pop ds
        mov al, 1
.r:     ret

; AL from thru_pause: when the last pause ends, the stage resumes once the UI
; is idle and no pause came for THRU_QUIET ticks (thru_idle), so a run of disk
; sectors or transfer chunks stays silent instead of re-keying between them.
; Keeps every register and the flags.
thru_resume:
        or al, al
        jz .r
        push ax
        push ds
        dec byte [cs:thru_hold]
        jnz .p
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        mov ax, [LC_TICKS]
        mov [cs:thru_quiet_at], ax
        mov byte [cs:thru_pending], 1
.p:     pop ds
        pop ax
.r:     ret

; Near, from thru_idle: the deferred resume.  DS = DGROUP.  Keeps every register.
thru_idle_resume:
        cmp byte [cs:thru_hold], 0
        jne .r
        push ax
        mov ax, [LC_TICKS]
        sub ax, [cs:thru_quiet_at]
        cmp ax, THRU_QUIET
        pop ax
        jb .r
        mov byte [cs:thru_pending], 0
        cmp byte [cs:thru_in_on], 0
        je .r
        cmp byte [cs:thru_stage_on], 0
        jne .r
        pusha
        call thru_stage_start
        popa
.r:     ret

; ---------------------------------------------------------------- hooks

; JMP from the allocator's free return 205E:00EC (image 0x206CC; Vailixi
; CF37:00E6), channel [bp-2] has a zero stop timer.  A reserved channel is
; passed over: its local timer copy zeroed (the >=3-voice pass), no candidate
; or histogram update, on to the next channel at 205E:0174 (inc cx).
thru_alloc_free:
        mov bx, [bp-2]
        cmp byte [cs:thru_resv+bx], 0
        jne .skip
        mov ax, bx                      ; the replaced instructions
        inc ax
        mov [ALLOC_NEXT], ax
        FJMP T_CF37_00ED                ; mov ax,[bp-2] / return it
.skip:  shl bx, 1
        add bx, bp
        mov word [ss:bx-0x48], 0
        FJMP T_CF37_016E

; JMP from the one-channel stop 234D:0000 (image 0x234D0; Vailixi D21F:0008):
; a reserved channel is left running (stop-all, MONO/Cutoff, cave stops).
thru_stop_guard:
        push bp
        mov bp, sp
        mov bx, [bp+6]
        cmp bx, 32
        jae .stock
        cmp byte [cs:thru_resv+bx], 0
        jne .skip
.stock: mov dx, 1                       ; the replaced instruction
        FJMP T_D21F_000E
.skip:  pop bp
        retf

; JMP from the wave transfer 20BA:0002 (image 0x20BA2; Vailixi CF92:000C):
; it reprograms ch3 and channel 0 and ends with port 68h = 80h, so the stage
; is paused around it.  Same seven arguments and AX result.
thru_xfer_guard:
        cmp byte [cs:thru_in_on], 0
        jne .wrap
        push bp                         ; the replaced instructions
        mov bp, sp
        sub sp, 0x0E
        FJMP T_CF92_0012
.wrap:  push bp
        mov bp, sp
        call thru_pause
        push ax
        push word [bp+18]
        push word [bp+16]
        push word [bp+14]
        push word [bp+12]
        push word [bp+10]
        push word [bp+8]
        push word [bp+6]
        push cs
        call .body
        add sp, 14
        xchg ax, [bp-2]                 ; keep the result, AL = the pause flag
        call thru_resume
        pop ax
        pop bp
        retf
.body:  push bp
        mov bp, sp
        sub sp, 0x0E
        FJMP T_CF92_0012

; FAR, in place of CALLF 2338:0000 in the MIDI sample dump (images 0x231E7,
; 0x23228): its reg-1 reset of all 32 channels runs with the stage paused.
; BX is its input; registers as 2338:0000 leaves them (AX, CX, DX).
thru_reg1_guard:
        call thru_pause
        push ax
        FCALL T_D20A_0008
        pop ax
        call thru_resume
        retf

; FAR from the floppy BIOS (INT 40 = 0009:1B32, the 3.16 BIOS copy), in place
; of MOV BP,SP / MOV DI,6097h at 0009:1B3C (image 0x1BCC): every floppy
; transfer masks DMA ch0, 2 and 3 (0009:1E94, 0009:1F07), and the audio DMA
; may not run beside it, so the stage is paused until thru_fdc_leave.
; AX (the INT 40 function) and the pushed frame are the caller's.
thru_fdc_enter:
        push ax
        call thru_pause
        mov [cs:thru_fdc_held], al
        pop ax
        mov di, FDC_DS_SEG              ; the replaced instructions
        RELOC_PREV
        mov bp, sp
        add bp, 4                       ; BP = the handler's SP before this call
        retf

; FAR from 0009:1B64 (image 0x1BF4), in place of MOV AH,[0007h] / OR AH,AH:
; the handler's result, then the stage resumes.  DS = the BIOS data segment.
thru_fdc_leave:
        push ax
        mov al, [cs:thru_fdc_held]
        call thru_resume
        pop ax
        mov ah, [0x0007]                ; the replaced instructions; RETF keeps the flags
        or ah, ah
        retf

; FAR from the key wait 2D0B:002B (image 0x2D0DB; Vailixi D6E0:0029), in place
; of TEST WORD [ES:BX+2],0FFFFh: the UI task spins here while no key is
; queued (it is reached from 0F6B:0009, the field editor's key fetch), the
; place for the deferred resume.  ES:BX and the test's flags are stock's.
thru_idle:
        cmp byte [cs:thru_pending], 0
        je .test
        push ds
        push ax
        mov ax, DGROUP_SEG
        RELOC_PREV
        mov ds, ax
        call thru_idle_resume
        pop ax
        pop ds
.test:  test word [es:bx+2], 0xFFFF     ; the replaced instruction; RETF keeps its flags
        retf

; FAR from the mode loop 15AC:0012 (image 0x15AD2; Vailixi C425:0012), in
; place of CALLF 02D7:0007: every mode change, the first one after the boot
; parameter load included, brings Thru to its settings.
thru_mode_hook:
        FCALL T_B060_000D
        call thru_sync
        retf

; FAR from 19F9:00BD (image 0x1A04D; Vailixi C887:00B7), in place of CALLF
; 1849:000F: Sample New Sound uses the same channels, DMA and 8255 bits, so
; Thru is off while it runs and comes back after.  AL = its result.
thru_sample_wrap:
        inc byte [cs:thru_hold]
        pusha
        call thru_input_stop
        popa
        FCALL T_C6C2_000B
        dec byte [cs:thru_hold]
        call thru_sync
        retf

; ---------------------------------------------------------------- Mixer page

; FAR from 1650:0013 (image 0x16513): the Mixer menu with "6.Input thru".
thru_menu_text:
        mov bx, thru_s_menu
        call du_put
        retf

; JMP from 1650:004D (image 0x1654D; Vailixi C4C8:0059), AL = option, already
; in [OPTION].  Options 1-5 go on as stock; 6 opens the page.
thru_menu_dispatch:
        cmp al, 6
        je .page
        cbw                             ; the replaced instructions
        dec ax
        mov bx, ax
        cmp bx, 4
        FJMP T_C4C8_0060                ; ja exit / option table
.page:  call thru_page
        mov dl, al
        FJMP T_C4C8_0094                ; mov al,dl / return the key

; Near.  The Input Thru page: Thru and Input choice fields, Level 0-100.  Each
; change is applied at once.  AX = the key that leaves the field editor.
thru_page:
        push si
        mov al, [THRU_LEVEL]
        xor al, THRU_LEVEL_DEF
        cmp al, 100
        jbe .lvl
        mov al, 100
.lvl:   mov [cs:thru_level_shown], al
        mov bx, thru_s_title
        call du_title
        mov al, 1
        call du_at
        push byte 8
        push cs
        push thru_modes
        push ds
        push THRU_MODE
        push cs
        push thru_s_thru
        FCALL T_B354_01C6
        add sp, 14
        mov ax, 0x1401                  ; (1, 20)
        call du_rc
        push byte 7
        push ds
        push THRU_INPUTS
        push ds
        push THRU_INPUT
        push cs
        push thru_s_input
        FCALL T_B354_01C6
        add sp, 14
        mov al, 2
        call du_at
        push byte 8                     ; byte storage
        push byte 100
        push byte 0
        push byte 3
        push cs
        push thru_level_shown
        push cs
        push thru_s_level
        FCALL T_B354_03B1
        add sp, 16
        mov bx, thru_s_none
        call du_keys
.key:   call thru_status_row
        push byte 0
        FCALL T_B060_035D
        add sp, 2
        or ax, ax
        jnz .leave
        mov al, [cs:thru_level_shown]   ; a field changed: store, save, apply
        xor al, THRU_LEVEL_DEF
        mov [THRU_LEVEL], al
        mov byte [TC_NV_DIRTY], 1
        call thru_sync
        jmp .key
.leave: pop si
        ret

; Row 4: "Status:" and the engine's state.  Changes AX, BX, flags.
thru_status_row:
        mov al, 4
        mov bx, thru_s_status
        call du_row_put
        mov bl, [cs:thru_status]
        mov bh, 0
        shl bx, 1
        mov bx, [cs:thru_s_states+bx]
        call du_put
        jmp du_eol

; ---------------------------------------------------------------- data

thru_modes:                             ; choice list: 0 OFF .. 3 STEREO (stock strings)
        dw XP_STR_OFF, DGROUP_SEG
        RELOC_PREV
        dw S_MONO_LFT, DGROUP_SEG
        RELOC_PREV
        dw S_MONO_RGT, DGROUP_SEG
        RELOC_PREV
        dw S_STEREO, DGROUP_SEG
        RELOC_PREV
        dd 0
thru_s_states:  dw thru_s_off, thru_s_on, thru_s_nolock, thru_s_nomem

thru_s_menu:    db "1.Stereo out mixer", 10, "2.Individual outs / effects mixer", 10
                db "3.All mix data (text)", 10, "4.Mixer source select, automated mix", 10
                db "5.Effects           6.Input thru", 0
thru_s_title:   db "Input Thru", 0
thru_s_thru:    db "Thru:", 0
thru_s_input:   db "Input:", 0
thru_s_level:   db "Level:", 0
thru_s_status:  db "Status:", 0
thru_s_off:     db "OFF", 0
thru_s_on:      db "ON", 0
thru_s_nolock:  db "NO DIGITAL LOCK", 0
thru_s_nomem:   db "NO SOUND MEMORY", 0
thru_s_none:    db 0

align 16
thru_cpu_ring:  times THRU_CPU_WORDS dw 0
thru_cpu_ring_end:
; The ring must not cross a 64 KB physical page (DMA address bits 23..16 are
; programmed once per restart).
        times -(((THRU_RUN_SEG * 16 + (thru_cpu_ring - $$)) >> 16) != ((THRU_RUN_SEG * 16 + (thru_cpu_ring_end - $$) - 1) >> 16)) db 0
