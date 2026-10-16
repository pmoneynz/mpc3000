; MPC2000XL-style shared zone boundaries, adapted to the 3000 wave view.
; One active Edit Sound session owns this map. Each zone uses boundaries
; [current-1,current]; the selected pair is mirrored to stock ZONE_ST/EN.
; RAM lives in our relocated, writable cave, never in unowned DGROUP space.

ZONE_MAX equ 16

; D6E0:0075 appends a key to KEY_QUEUE, which is not strong enough for the
; one-shot resume contract: an older queued mode key could run first.
; FB00's unget helper (T_FB00_06B9) inserts at the read head, so the
; synthetic '6' is the next key consumed.

; New stock Edit Sound invocation starts a new map lifetime, unless it is
; the explicit waveform Exit/Help re-entry into the same page.
zones_page_entry:
        push bp
        mov bp, sp
        sub sp, 0x2C0
        cmp byte [cs:zones_resume], 0
        jne .resume
        mov byte [cs:zones_valid], 0
        mov byte [cs:zones_reselect], 0
        jmp .clear
.resume:
        mov byte [cs:zones_reselect], 1
.clear:
        mov byte [cs:zones_resume], 0
        FJMP T_B99A_0009

; Replaces B99A:[0063,006B), immediately after 27F2 builds the sorted Sound
; list at SS:[BP-BC].  Stock restores a sorted-list position from a global,
; but CHOP ZONE can insert names before the selected source.  On the one-shot
; waveform re-entry, resolve the retained source record to its new position.
; A found position is also written to the word global, as stock B99A:04E9
; does (CBW of 0..127 = BX), so the stock `cmp [E40A],di` at 006B keeps it
; and a later fresh page entry restores the same Sound.
; AH, BX and CX retain the stock seam's incoming values.
zones_list_ready:
        mov di, ax
        mov al, [LIST_SELECTION]
        cmp byte [cs:zones_reselect], 0
        je .store
        mov byte [cs:zones_reselect], 0
        cmp di, -1
        je .store
        push bx
        push cx
        push si
        mov cl, al
        mov al, [cs:zones_source]
        xor bx, bx
.scan: cmp bx, di
        jae .not_found
        lea si, [bp-0xBC]
        add si, bx
        cmp al, [ss:si]
        je .found
        inc bx
        jmp .scan
.found:mov cl, bl
        mov [LIST_SELECTION], bx
.not_found:
        mov al, cl
        pop si
        pop cx
        pop bx
.store:mov [bp-2], al
        FJMP T_B99A_006B

; Replaces the field-0 handler's initial cmp/jump window.  A sound-selection
; commit invalidates even when the user later selects the original slot:
; stock ZONE_ST/EN are global and may already have been clamped for the
; intervening sound, so they no longer carry source provenance.
zones_sound_changed:
        mov byte [cs:zones_valid], 0
        mov byte [cs:zones_resume], 0
        cmp di, -1
        jne .have_sound
        FJMP T_B99A_082E
.have_sound:
        FJMP T_B99A_04E3

; Put option '6' at the front of the stock key queue and arm exactly one
; Edit Sound re-entry.  FB00 returns -1 when the queue is already full, 0 on
; ordinary success, and 1 when this insertion fills the final slot.  Failure
; safely loses the map and leaves the user at Program/Sounds; it must never
; leave a stale resume token for a later Edit Sound invocation.
;
; Preserve every caller-visible register and the incoming flags.
zones_reopen:
        pushf
        push ax
        push bx
        push cx
        push es
        push ds
        pop es
        mov bx, KEY_QUEUE
        mov cl, '6'
        FCALL T_FB00_06B9
        or ax, ax
        js .failed
        mov byte [cs:zones_resume], 1
        jmp .done
.failed:
        mov byte [cs:zones_resume], 0
        mov byte [cs:zones_reselect], 0
        mov byte [cs:zones_valid], 0
.done:  pop es
        pop cx
        pop bx
        pop ax
        popf
        ret

%ifdef PROFILE_316
; Replaces 0B72:[1212,121B) (Vailixi B99A:[159E,15A7)), the page exit's
; TEMPORARY999 lookup.  A waveform Exit/Help leaves the page only to re-enter
; it (zones_reopen armed zones_resume): keep TEMPORARY999 then.
zones_exit_temp:
        cmp byte [cs:zones_resume], 0
        jne .keep
        push ds
        push EDITDO_TEMP_NAME
        FCALL T_D0C0_0D17
        FJMP T_B99A_15A7
.keep:  FJMP T_B99A_15BE
%endif

; Current source is rec/sound_index/len/wbase/stereo. Preserve all registers.
; A different descriptor identity starts a fresh whole-sound division.
zones_enter:
        pusha
        push es
        mov ax, SND_SEG
        RELOC_PREV
        mov es, ax
        mov si, [cs:rec]
        cmp byte [cs:zones_valid], 0
        je .new
        mov ax, [cs:sound_index]
        cmp ax, [cs:zones_source]
        jne .new
        xor bx, bx
.name: mov al, [es:si+bx]
        cmp al, [cs:zones_identity+bx]
        jne .new
        inc bx
        cmp bx, 16
        jb .name
        mov al, [es:si+0x13]
        cmp al, [cs:zones_identity+16]
        jne .new
        mov bx, 0x1C
        mov di, zones_identity+17
.tail: mov al, [es:si+bx]
        cmp al, [cs:di]
        jne .new
        inc bx
        inc di
        cmp bx, 0x24
        jb .tail
        ; Stock Edit Sound may have edited the active pair since our exit.
        call zones_import
        jmp .done
.new:  mov ax, [cs:sound_index]
        mov [cs:zones_source], ax
        xor bx, bx
.copy: mov al, [es:si+bx]
        mov [cs:zones_identity+bx], al
        inc bx
        cmp bx, 16
        jb .copy
        mov al, [es:si+0x13]
        mov [cs:zones_identity+16], al
        mov bx, 0x1C
        mov di, zones_identity+17
.ctail:mov al, [es:si+bx]
        mov [cs:di], al
        inc bx
        inc di
        cmp bx, 0x24
        jb .ctail
        mov byte [cs:zones_count], ZONE_MAX
        mov byte [cs:zones_current], 1
        mov byte [cs:zones_valid], 1
        call zones_divide
.done: pop es
        popa
        ret

; B[i] = floor(i * length / count), i=0..count; length < 2^24.
; Use a quotient/remainder accumulator, avoiding 32-bit multiply overflow.
zones_divide:
        pusha
        xor cx, cx
        mov cl, [cs:zones_count]
        xor dx, dx
        mov ax, [cs:len+2]
        div cx
        mov [cs:zones_quotient+2], ax
        mov ax, [cs:len]
        div cx
        mov [cs:zones_quotient], ax
        mov [cs:zones_remainder], dx
        xor ax, ax
        xor dx, dx
        xor bx, bx
        mov di, zones_bounds
        mov [cs:di], ax
        mov [cs:di+2], dx
.next: add ax, [cs:zones_quotient]
        adc dx, [cs:zones_quotient+2]
        add bx, [cs:zones_remainder]
        push cx
        xor cx, cx
        mov cl, [cs:zones_count]
        cmp bx, cx
        jb .store
        sub bx, cx
        add ax, 1
        adc dx, 0
.store:pop cx
        add di, 4
        mov [cs:di], ax
        mov [cs:di+2], dx
        loop .next
        mov al, [cs:zones_current]
        cmp al, [cs:zones_count]
        jbe .load
        mov al, [cs:zones_count]
        mov [cs:zones_current], al
.load: call zones_load
        popa
        ret

; BX = offset of the current zone's start boundary in our table.
zones_offset:
        xor bx, bx
        mov bl, [cs:zones_current]
        dec bx
        shl bx, 1
        shl bx, 1
        add bx, zones_bounds
        ret

zones_load:
        pusha
        call zones_offset
        mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        mov [ZONE_ST], ax
        mov [ZONE_ST+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        mov [ZONE_EN], ax
        mov [ZONE_EN+2], dx
        popa
        ret

 ; Import stock page edits atomically, clamped to the two outer neighbors.
; This also handles both endpoints moving below/above their old positions.
zones_import:
        pusha
        call zones_offset
        xor ax, ax
        xor dx, dx
        cmp byte [cs:zones_current], 1
        je .low
        mov ax, [cs:bx-4]
        mov dx, [cs:bx-2]
.low:   mov [cs:lo], ax
        mov [cs:lo+2], dx
        mov ax, [cs:len]
        mov dx, [cs:len+2]
        mov cl, [cs:zones_current]
        cmp cl, [cs:zones_count]
        je .high
        mov ax, [cs:bx+8]
        mov dx, [cs:bx+10]
.high:  mov [cs:hi], ax
        mov [cs:hi+2], dx
        mov ax, [ZONE_ST]
        mov dx, [ZONE_ST+2]
        call zones_clamp
        mov [cs:bx], ax
        mov [cs:bx+2], dx
        mov [cs:lo], ax
        mov [cs:lo+2], dx
        mov ax, [ZONE_EN]
        mov dx, [ZONE_EN+2]
        call zones_clamp
        mov [cs:bx+4], ax
        mov [cs:bx+6], dx
        call zones_load
        popa
        ret

zones_clamp:
        cmp dx, [cs:lo+2]
        jb .low
        ja .high
        cmp ax, [cs:lo]
        jae .high
.low:   mov ax, [cs:lo]
        mov dx, [cs:lo+2]
        ret
.high:  cmp dx, [cs:hi+2]
        ja .sethigh
        jb .done
        cmp ax, [cs:hi]
        jbe .done
.sethigh:
        mov ax, [cs:hi]
        mov dx, [cs:hi+2]
.done:  ret

; Tighten move's outer clamp to the adjacent zone boundary.
zones_limits:
        test byte [cs:sel], 2
        jz .done
        call zones_offset
        test byte [cs:sel], 1
        jnz .end
        cmp byte [cs:zones_current], 1
        je .done
        mov ax, [cs:bx-4]
        mov dx, [cs:bx-2]
        mov [cs:lo], ax
        mov [cs:lo+2], dx
        ret
.end:  mov al, [cs:zones_current]
        cmp al, [cs:zones_count]
        je .done
        mov ax, [cs:bx+8]
        mov dx, [cs:bx+10]
        mov [cs:hi], ax
        mov [cs:hi+2], dx
.done: ret

; Called after move writes a selected endpoint. Preserve its output values.
zones_store:
        test byte [cs:sel], 2
        jz .done
        push bx
        call zones_offset
        test byte [cs:sel], 1
        jz .write
        add bx, 4
.write:mov [cs:bx], ax
        mov [cs:bx+2], dx
        pop bx
.done: ret

; BL is '+' or '-'; onview 2 selects current, 3 selects total.
zones_adjust:
        mov al, [cs:zones_current]
        mov cl, [cs:zones_count]
        mov di, zones_current
        cmp byte [cs:onview], 2
        je .change
        mov di, zones_count
        mov al, [cs:zones_count]
        mov cl, ZONE_MAX
.change:
        mov dx, [cs:key_repeat]
        or dx, dx
        jnz .repeat_ready
        inc dx
.repeat_ready:
        cmp bl, '+'
        jne .minus
        cmp al, cl
        jae .done
.plus: inc al
        dec dx
        jz .set
        cmp al, cl
        jb .plus
        jmp .set
.minus:cmp al, 1
        jbe .done
 .minus_loop:
        dec al
        dec dx
        jz .set
        cmp al, 1
        ja .minus_loop
.set:  mov [cs:di], al
        mov byte [cs:sel], 2
        cmp byte [cs:onview], 3
        jne .load
        call zones_divide
        ret
.load: call zones_load
.done: ret

zones_title:
        xor ax, ax
        mov al, [cs:zones_current]
        mov di, s_zones+5
        mov cx, 2
        call digits
        xor ax, ax
        mov al, [cs:zones_count]
        mov di, s_zones+8
        mov cx, 2
        call digits
        xor ax, ax
        mov bx, 30
        mov si, s_zones
        call text
        ret

zones_focus:
        mov bx, 35*6
        cmp byte [cs:onview], 2
        je .draw
        mov bx, 38*6
.draw: xor ax, ax
        mov cx, 12
        mov dx, 7
        jmp invert

s_zones: db "ZONE:01/16", 0
zones_valid: db 0
zones_resume: db 0
zones_reselect: db 0
zones_count: db 16
zones_current: db 1
zones_identity: times 25 db 0
align 2
zones_source: dw 0
zones_bounds: times ZONE_MAX+1 dd 0
zones_quotient: dd 0
zones_remainder: dw 0
