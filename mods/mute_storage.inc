; Program-owned MUTE GROUPS state and PGM/APS trailer persistence.
;
; Evidence and hook addresses: notes/mute_storage.md.
; This include is assembled in the shared F07D cave.  All mutable bytes are
; CS-relative because DGROUP has no proven spare allocation.
;
; Public API (all preserve SI, DI, BP and DS; AX/BX/CX/DX/ES may change):
;   mute_get_enabled: AL=program 0..23                 -> AL=0/1
;   mute_get_group:   AL=program 0..23, BL=pad 0..63  -> AL=0..4
;   mute_set_enabled: AL=program, DL=0/1
;   mute_set_group:   AL=program, BL=pad, DL=0..4
;   mute_apply_all:   AL=program, DL=0..4
;
; Groups use one nibble per pad (0=Off, 1..4=Group 1..4).  A program state
; is one enabled byte followed by 32 packed group bytes.  The API hides the
; packing from the UI and voice path.

MUTE_STORAGE_PROGRAM_COUNT equ 24
MUTE_STORAGE_PAD_COUNT     equ 64
MUTE_STORAGE_GROUP_BYTES   equ 32
MUTE_STORAGE_STATE_BYTES   equ 33
MUTE_STORAGE_ALL_BYTES     equ MUTE_STORAGE_PROGRAM_COUNT * MUTE_STORAGE_STATE_BYTES
MUTE_STORAGE_HEADER_BYTES  equ 16

; ---------------------------------------------------------------- public API

mute_get_enabled:
        push si
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .invalid
        call mute_state_bx
        mov al, [cs:bx]
        pop si
        ret
.invalid:
        xor al, al
        pop si
        ret

mute_get_group:
        push si
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .invalid
        cmp bl, MUTE_STORAGE_PAD_COUNT
        jae .invalid
        mov cl, bl
        call mute_state_bx
        mov al, cl
        shr al, 1
        xor ah, ah
        add bx, ax
        mov al, [cs:bx+1]
        test cl, 1
        jnz .high
        and al, 0x0F
        pop si
        ret
.high:  shr al, 4
        pop si
        ret
.invalid:
        xor al, al
        pop si
        ret

mute_set_enabled:
        push si
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .done
        cmp dl, 1
        ja .done
        call mute_state_bx
        mov [cs:bx], dl
.done: pop si
        ret

mute_set_group:
        push si
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .done
        cmp bl, MUTE_STORAGE_PAD_COUNT
        jae .done
        cmp dl, 4
        ja .done
        mov cl, bl
        call mute_state_bx
        mov al, cl
        shr al, 1
        xor ah, ah
        add bx, ax
        mov al, [cs:bx+1]
        test cl, 1
        jnz .high
        and al, 0xF0
        or al, dl
        mov [cs:bx+1], al
        jmp .done
.high:  and al, 0x0F
        mov ah, dl
        shl ah, 4
        or al, ah
        mov [cs:bx+1], al
.done: pop si
        ret

mute_apply_all:
        push si
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .done
        cmp dl, 4
        ja .done
        call mute_state_bx
        inc bx
        mov al, dl
        mov ah, dl
        shl ah, 4
        or al, ah
        mov cx, MUTE_STORAGE_GROUP_BYTES
.fill: mov [cs:bx], al
        inc bx
        loop .fill
.done: pop si
        ret

; AL=program, return CS:BX state pointer.  Caller has validated AL.
mute_state_bx:
        xor ah, ah
        mov bx, ax
        shl ax, 5
        add bx, ax                         ; program * 33
        add bx, mute_states
        ret

; AL=program.  Invalid values are ignored.
mute_clear_program:
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .done
        call mute_state_bx
        mov cx, MUTE_STORAGE_STATE_BYTES
.zero: mov byte [cs:bx], 0
        inc bx
        loop .zero
.done: ret

; ---------------------------------------------------------------- lifecycle hooks

; Replaces CF37:[04AD,04B3), linear 0x4F81D:
;   55 8B EC 83 EC 04
; Recreate the prologue, forget voices tagged with the old program identity,
; clear its mod state, and rejoin before the stock SI/DI saves.
mute_program_init_hook:
        push bp
        mov bp, sp
        sub sp, 4
        pushf
        push ax
        push bx
        push cx
        push dx
        mov al, [bp+6]
        call mute_forget_program
        mov al, [bp+6]
        call mute_clear_program
        pop dx
        pop cx
        pop bx
        pop ax
        popf
        FJMP T_CF37_04B3

; Replaces C887:[19F2,19FB), linear 0x4A262:
;   B9 BF 03 1E 8E D8 F3 A5 1F
; Preserve the stock full-record copy, then copy the source program's mod
; state.  Source=[BP-1]-1, destination=[BP-2]-1 on this proven UI arm.
; Both are numeric fields clamped to 1..24 by B31B:0214, so the range test
; is defensive.  An out-of-range index skips only the mod-state work; the
; stock copy has already run and CX is still its final 0.
mute_program_copy_hook:
        mov cx, 0x03BF
        push ds
        mov ds, ax
        rep movsw
        pop ds
        pushf
        push ax
        push bx
        push dx
        push si
        push di
        mov al, [bp-1]
        dec al                             ; 0 wraps to FF and is rejected
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .skip
        call mute_state_bx
        mov si, bx
        mov al, [bp-2]
        dec al
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae .skip
        call mute_state_bx
        mov di, bx
        mov al, [bp-2]
        dec al
        call mute_forget_program           ; preserves SI and DI
        mov cx, MUTE_STORAGE_STATE_BYTES
.copy: mov al, [cs:si]
        mov [cs:di], al
        inc si
        inc di
        loop .copy
.skip: pop di
        pop si
        pop dx
        pop bx
        pop ax
        popf
        FJMP T_C887_19FB

; ---------------------------------------------------------------- persistence hooks

; These four far cdecl wrappers replace CEE6:0086 close calls.  The caller
; has already pushed the handle at [BP+6] and still performs ADD SP,2.
; The PGM wrappers range-check their one-based program argument.  Every
; stock caller supplies 1..24 (notes/mute_storage.md), so the check is
; defensive: an out-of-range value performs exactly the stock close and
; returns its AX/DX, with no trailer read, write, or state change.

; Wrapper tail: BP is the wrapper frame with SI and DI pushed.
mute_close_only:
        push word [bp+6]
        FCALL T_CEE6_0086
        add sp, 2
        pop di
        pop si
        pop bp
        retf

; PGM load close: C20F:0412, linear 0x42502.
mute_pgm_load_close:
        push bp
        mov bp, sp
        push si
        push di
        ; C20F:0003's stable one-based destination is [caller BP+0Ah].
        ; Do not use the asynchronously mutable selected-program byte here.
        mov bx, [bp]
        mov al, [ss:bx+0x0A]
        dec al                             ; 0 wraps to FF and is rejected
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jae mute_close_only
        xor ah, ah
        mov si, ax                         ; preserved by both callees
        call mute_forget_program
        mov ax, si
        call mute_clear_program
        mov ax, si
        call mute_state_bx
        mov di, bx
        mov ax, [bp+6]
        mov si, mute_pgm_header
        mov cx, MUTE_STORAGE_STATE_BYTES
        mov dl, 1
        call mute_load_close_common
        pop di
        pop si
        pop bp
        retf

; APS load close: C20F:07CC, linear 0x428BC.
mute_aps_load_close:
        push bp
        mov bp, sp
        push si
        push di
        xor si, si
.clear:mov ax, si
        call mute_forget_program
        mov ax, si
        call mute_clear_program
        inc si
        cmp si, MUTE_STORAGE_PROGRAM_COUNT
        jb .clear
        ; C20F:04F6 stores the APS program count at [caller BP-3].  Match
        ; the trailer to the number of stock records actually loaded.
        mov bx, [bp]
        xor ax, ax
        mov al, [ss:bx-3]
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jbe .shape
        xor ax, ax
.shape: mov [cs:mute_aps_header+14], ax
        mov dx, ax
        mov cx, ax
        shl ax, 5
        add cx, ax                         ; count * 33
        mov ax, [bp+6]
        mov si, mute_aps_header
        mov di, mute_states
        call mute_load_close_common
        pop di
        pop si
        pop bp
        retf

; PGM save close: E7F5:09FE, linear 0x6894E.
mute_pgm_save_close:
        push bp
        mov bp, sp
        push si
        push di
        ; E7F5:079D's stable one-based source is [caller BP+06h].
        ; The stock body reads this argument as a word (E7F5:07B0), so test
        ; the word; 0 wraps to FFFF and is rejected.
        mov bx, [bp]
        mov ax, [ss:bx+0x06]
        dec ax
        cmp ax, MUTE_STORAGE_PROGRAM_COUNT
        jae mute_close_only
        call mute_state_bx
        mov di, bx
        mov ax, [bp+6]
        mov si, mute_pgm_header
        mov cx, MUTE_STORAGE_STATE_BYTES
        call mute_write_close_common
        pop di
        pop si
        pop bp
        retf

; APS save close: E7F5:0E5E, linear 0x68DAE.
mute_aps_save_close:
        push bp
        mov bp, sp
        push si
        push di
        ; E7F5:0BA7 stores the APS program count at [caller BP-3].
        mov bx, [bp]
        xor ax, ax
        mov al, [ss:bx-3]
        cmp al, MUTE_STORAGE_PROGRAM_COUNT
        jbe .shape
        xor ax, ax
.shape: mov [cs:mute_aps_header+14], ax
        mov cx, ax
        shl ax, 5
        add cx, ax                         ; count * 33
        mov ax, [bp+6]
        mov si, mute_aps_header
        mov di, mute_states
        call mute_write_close_common
        pop di
        pop si
        pop bp
        retf

; AX=handle, SI=expected header, DI=destination, CX=payload bytes,
; DL=state count.  Optional read failures and malformed trailers leave the
; already-cleared destination alone.  Return only the real close result so a
; legacy EOF cannot turn a valid stock program into a load error.
mute_load_close_common:
        push bp
        mov bp, sp
        sub sp, 10
        push bx
        push cx
        push dx
        push si
        push di
        mov [bp-2], ax                    ; handle
        mov [bp-4], si                    ; expected header
        mov [bp-6], di                    ; destination
        mov [bp-8], cx                    ; payload bytes
        mov [bp-10], dl                   ; state count
        push word MUTE_STORAGE_HEADER_BYTES
        push word [bp-2]
        push cs
        push word mute_read_header
        FCALL T_CF0C_0073
        add sp, 8
        or ax, ax
        jnz .close
        mov bx, mute_read_header
        mov si, [bp-4]
        mov cx, MUTE_STORAGE_HEADER_BYTES / 2
.header:
        mov ax, [cs:bx]
        cmp ax, [cs:si]
        jne .close
        add bx, 2
        add si, 2
        loop .header
        cmp word [bp-8], 0
        je .close
        push word [bp-8]
        push word [bp-2]
        push cs
        push word mute_staging
        FCALL T_CF0C_0073
        add sp, 8
        or ax, ax
        jnz .close
        xor cx, cx
        mov cl, [bp-10]
        call mute_validate_staging
        or ax, ax
        jz .close
        mov si, mute_staging
        mov di, [bp-6]
        mov cx, [bp-8]
.commit:
        mov al, [cs:si]
        mov [cs:di], al
        inc si
        inc di
        loop .commit
.close:push word [bp-2]
        FCALL T_CEE6_0086
        add sp, 2
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        mov sp, bp
        pop bp
        ret

; AX=handle, SI=header, DI=payload, CX=payload bytes.  Always close.  Return
; the first write error; when both writes succeed, return the close result.
mute_write_close_common:
        push bp
        mov bp, sp
        sub sp, 10
        push bx
        push cx
        push dx
        push si
        push di
        mov [bp-2], ax                    ; handle
        mov [bp-4], si                    ; header
        mov [bp-6], di                    ; payload
        mov [bp-8], cx                    ; payload bytes
        mov word [bp-10], 0               ; first error
        push word MUTE_STORAGE_HEADER_BYTES
        push word [bp-2]
        push cs
        push word [bp-4]
        FCALL T_CF0C_0096
        add sp, 8
        or ax, ax
        jz .payload
        mov [bp-10], ax
        jmp .close
.payload:
        cmp word [bp-8], 0
        je .close
        push word [bp-8]
        push word [bp-2]
        push cs
        push word [bp-6]
        FCALL T_CF0C_0096
        add sp, 8
        or ax, ax
        jz .close
        mov [bp-10], ax
.close:push word [bp-2]
        FCALL T_CEE6_0086
        add sp, 2
        cmp word [bp-10], 0
        je .return
        mov ax, [bp-10]
.return:
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        mov sp, bp
        pop bp
        ret

; CX=number of staged state records.  Return AX=1 only when every enabled
; byte is 0/1 and both nibbles of every packed group byte are 0..4.
mute_validate_staging:
        mov si, mute_staging
.state:mov al, [cs:si]
        cmp al, 1
        ja .bad
        inc si
        mov bx, MUTE_STORAGE_GROUP_BYTES
.group:mov al, [cs:si]
        mov ah, al
        and al, 0x0F
        cmp al, 4
        ja .bad
        mov al, ah
        shr al, 4
        cmp al, 4
        ja .bad
        inc si
        dec bx
        jnz .group
        loop .state
        mov ax, 1
        ret
.bad:  xor ax, ax
        ret

; ---------------------------------------------------------------- on-disk ABI and mutable state

; The stock loaders close after their fixed-size reads and ignore these
; trailing bytes.  Exact header matching provides version/kind/length/count
; validation before any staged state is committed.
mute_pgm_header:
        db 'MUTEGP35'
        db 1, 1                            ; kind=PGM, version=1
        dw MUTE_STORAGE_HEADER_BYTES
        dw MUTE_STORAGE_STATE_BYTES
        dw 1

mute_aps_header:
        db 'MUTEGP35'
        db 2, 1                            ; kind=APS, version=1
        dw MUTE_STORAGE_HEADER_BYTES
        dw MUTE_STORAGE_STATE_BYTES
        dw 0                               ; patched to the stock APS count

%ifdef PROFILE_316
mute_states:      times MUTE_STORAGE_ALL_BYTES db 0
; Session scratch shared by three users that never overlap: the wave view's
; column arrays and text buffers (wave.asm, one view() call), the mute page's
; context (mute_ui.inc, one mute_ui() call) and the load-close staging below
; (one mute_load_close_common call).  None reads a byte it has not written in
; the same call.  mute_staging stays at mute_state_bx(24) (test_mute_range).
mute_staging:
cave_pool:        times 4 * COLS + 28 db 0
mute_read_header  equ cave_pool + MUTE_STORAGE_ALL_BYTES
%else
mute_read_header: times MUTE_STORAGE_HEADER_BYTES db 0
mute_states:      times MUTE_STORAGE_ALL_BYTES db 0
mute_staging:     times MUTE_STORAGE_ALL_BYTES db 0
%endif
