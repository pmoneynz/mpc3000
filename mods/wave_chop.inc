; Multi-zone Sound creation for the WAVE Edit Sound extension.
;
; The two hook entries are reached by far JMPs from B99A.  chop_create_all
; is a near helper and deliberately keeps the suspended B99A page BP live.
; All mutable state is CS-relative because the F07D cave is copied to RAM.

CHOP_CAVE_SEG equ 0xF07D
CHOP_MIN_FRAMES equ 441
CHOP_ERR_EMPTY equ -0x0101
CHOP_ERR_MAP equ -0x0102
CHOP_ERR_SHORT equ -0x0103

; Stock Edit Sound safety bytes.  Every stock Do handler refuses through
; B99A:1595 when [A7AE] (transport state, meaning HYPOTHESIS) and the
; "safe lock" setting [862F] are both non-zero (B99A:0B2F..0B3D).  The
; copy wrapper B99A:1728 mutes through D980:000C while [8629] is set.  The
; capture shifts all three DGROUP operands by -2 (B99A:0B2F, B99A:1732).
%ifdef WAVE_CAPTURE_20261001
CHOP_SEQ_STATE equ 0xA7AC
CHOP_SAFE_LOCK equ 0x862D
CHOP_MUTE_EDIT equ 0x8627
CHOP_DO        equ 0xEDB3
CHOP_DO_LABEL  equ 0x377F
CHOP_OPT_0     equ 0x3630
CHOP_OPT_1     equ 0x3641
CHOP_OPT_2     equ 0x3652
CHOP_OPT_3     equ 0x3663
CHOP_OPT_4     equ 0x3674
CHOP_OPT_5     equ 0x3680
CHOP_OPT_6     equ 0x3691
CHOP_OPT_7     equ 0x36A2
CHOP_OPT_8     equ 0x36B3
CHOP_OPT_9     equ 0x36C0
%else
CHOP_SEQ_STATE equ 0xA7AE
CHOP_SAFE_LOCK equ 0x862F
CHOP_MUTE_EDIT equ 0x8629
CHOP_DO        equ 0xEDB5
CHOP_DO_LABEL  equ 0x3781
CHOP_OPT_0     equ 0x3632
CHOP_OPT_1     equ 0x3643
CHOP_OPT_2     equ 0x3654
CHOP_OPT_3     equ 0x3665
CHOP_OPT_4     equ 0x3676
CHOP_OPT_5     equ 0x3682
CHOP_OPT_6     equ 0x3693
CHOP_OPT_7     equ 0x36A4
CHOP_OPT_8     equ 0x36B5
CHOP_OPT_9     equ 0x36C2
%endif

; Replaces B99A:[046D,048F).  The stock ten-entry choice field is rebuilt
; with an eleventh entry.  Width remains the stock 16 characters.
chop_do_field:
        cmp byte [CHOP_DO], 11
        jb .index_ok
        mov byte [CHOP_DO], 0
.index_ok:
        push 16
        push CHOP_CAVE_SEG
        push chop_do_options
        push ds
        push CHOP_DO
        push ds
        push CHOP_DO_LABEL
        call 0xB354:0x01C6
        add sp, 14
        jmp 0xB99A:0x048F

; Replaces B99A:[0AFF,0B0D).  Values 0..9 rejoin the stock jump table;
; value 10 creates all mapped zones, refreshes the page's sound list, and
; reports a negative result through the same stock error path as Copy Zone.
chop_do_dispatch:
        mov al, [CHOP_DO]
        xor ah, ah
        mov bx, ax
        cmp bx, 9
        jbe .stock
        cmp bx, 10
        jne .leave
        ; The stock handlers' safe-lock refusal, before any state is touched.
        cmp byte [CHOP_SEQ_STATE], 0
        je .unlocked
        cmp byte [CHOP_SAFE_LOCK], 0
        jne .leave
.unlocked:
        ; Keep the page's current selection even when an old map is rejected.
        ; zones_source may belong to a different sound on this error path.
        xor ax, ax
        mov al, [ss:bp-2]
        lea si, [bp-0x0BC]
        add si, ax
        mov al, [ss:si]
        mov [cs:chop_selected_record], al
        call chop_create_all
        or ax, ax
        jns .refresh
        cmp ax, CHOP_ERR_EMPTY
        je .empty_zone
        cmp ax, CHOP_ERR_MAP
        je .stale_map
        cmp ax, CHOP_ERR_SHORT
        je .short_zone
        mov si, ax
        call 0xB1B1:0x004F
        neg si
        push si
        call 0xB3C7:0x0007
        add sp, 2
        call 0xB1B1:0x0055
        jmp .refresh
.empty_zone:
        mov si, chop_empty_text
        call chop_show_status
        jmp .refresh
.stale_map:
        mov si, chop_stale_text
        call chop_show_status
        jmp .refresh
.short_zone:
        mov si, chop_short_text
        call chop_show_status
.refresh:
        push 0
        push ss
        lea ax, [bp-0x2C0]
        push ax
        push ss
        lea ax, [bp-0x0BC]
        push ax
        call 0xB99A:0x27F2
        add sp, 10
        ; Allocation fills the lowest free record, so rebuilding the sorted
        ; list can shift the selection. Find the previous record before redraw uses
        ; [BP-2] as the selected list position.  Like stock B99A:04E9, also
        ; save it as the word global read by the next page entry; positions
        ; are 0..127 (B99A:282A), so BX equals stock's CBW form.
        or ax, ax
        jle .redraw
        mov cx, ax
        lea si, [bp-0x0BC]
        xor bx, bx
.find_source:
        mov dl, [ss:si]
        xor dh, dh
        cmp dl, [cs:chop_selected_record]
        je .source_found
        inc si
        inc bx
        loop .find_source
        jmp .redraw
.source_found:
        mov [bp-2], bl
        mov [LIST_SELECTION], bx
.redraw:
        call 0xB99A:0x16BB
.leave: jmp 0xB99A:0x1595
.stock:
        mov byte [cs:zones_valid], 0
        mov byte [cs:zones_resume], 0
        jmp 0xB99A:0x0B0D

; Lifecycle hook for D0C0:[0B19,0B1F).  It recreates the replaced
; prologue, invalidates a map before its source record is deleted, and then
; rejoins the original routine.  AX is dead at the rejoin point.
chop_sound_delete:
        push bp
        mov bp, sp
        sub sp, 6
        mov ax, [bp+6]
        cmp ax, [cs:zones_source]
        jne .keep
        mov byte [cs:zones_valid], 0
.keep:  jmp 0xD0C0:0x0B1F

; Create one collision-safe ZONE Sound for every [B[i],B[i+1]) interval.
; Returns AX=0, or a negative stock-style error.  The operation preflights
; descriptor identity, exact boundaries, free records and free wave words.
; Allocator failures roll back every record created by this invocation.
chop_create_all:
        push bx
        push cx
        push dx
        push si
        push di
        push ds
        push es
        mov word [cs:chop_result], CHOP_ERR_MAP
        mov byte [cs:chop_created_count], 0

        cmp byte [cs:zones_valid], 1
        jne .return
        xor cx, cx
        mov cl, [cs:zones_count]
        cmp cx, 1
        jb .return
        cmp cx, ZONE_MAX
        ja .return
        xor ax, ax
        mov al, [cs:zones_current]
        cmp ax, 1
        jb .return
        cmp ax, cx
        ja .return

        ; Resolve the page's live selected-sound index.  A map made for a
        ; previously selected record must never be applied to the new one.
        xor ax, ax
        mov al, [ss:bp-2]
        mov bx, bp
        sub bx, 0x0BC
        add bx, ax
        mov al, [ss:bx]
        xor ah, ah
        cmp ax, [cs:zones_source]
        jne .return

        ; Recheck the source identity saved by zones_enter: name, stereo,
        ; length and base.  The base is refreshed after our own allocations.
        call chop_source_record
        xor si, si
.name_identity:
        mov al, [es:bx+si]
        cmp al, [cs:zones_identity+si]
        jne .return
        inc si
        cmp si, 16
        jb .name_identity
        mov al, [es:bx+0x13]
        cmp al, [cs:zones_identity+16]
        jne .return
        cmp al, 1
        ja .return
        xor si, si
.tail_identity:
        mov al, [es:bx+si+0x1C]
        cmp al, [cs:zones_identity+si+17]
        jne .return
        inc si
        cmp si, 8
        jb .tail_identity
        mov al, [es:bx+0x13]
        mov [cs:chop_source_stereo], al
        mov al, [es:bx+0x11]
        mov [cs:chop_source_volume], al
        mov al, [es:bx+0x12]
        mov [cs:chop_source_tune], al
        mov ax, [es:bx+0x1C]
        mov dx, [es:bx+0x1E]
        mov [cs:chop_source_len], ax
        mov [cs:chop_source_len+2], dx

        ; Import any stock Edit Sound changes made to the active pair since
        ; leaving the waveform view.  Identity and current/count bounds have
        ; already been checked, so zones_offset cannot escape the table.
        call zones_import

        ; The editable domain is [B[0],B[N]] within the source.  Every
        ; interval must be positive and at least 441 frames.  D0C0:0611
        ; allocates a smaller caller count but clamps record +1C to 441; the
        ; stock SND loader repeats that mismatch on reload, so shorter exact
        ; Sounds are not persistent-safe without a separate loader patch.
        mov ax, [cs:zones_bounds]
        mov dx, [cs:zones_bounds+2]
        cmp dx, [cs:chop_source_len+2]
        ja .return
        jb .first_in_range
        cmp ax, [cs:chop_source_len]
        ja .return
.first_in_range:
        mov word [cs:chop_required], 0
        mov word [cs:chop_required+2], 0
        xor si, si
.validate_zone:
        mov bx, si
        shl bx, 1
        shl bx, 1
        add bx, zones_bounds
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        cmp dx, [cs:bx+2]
        jb .empty
        ja .positive_zone
        cmp ax, [cs:bx]
        jbe .empty
.positive_zone:
        sub ax, [cs:bx]
        sbb dx, [cs:bx+2]
        cmp dx, 0
        jne .zone_long_enough
        cmp ax, CHOP_MIN_FRAMES
        jb .short
.zone_long_enough:
        cmp byte [cs:chop_source_stereo], 0
        je .add_required
        shl ax, 1
        rcl dx, 1
.add_required:
        add [cs:chop_required], ax
        adc [cs:chop_required+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        cmp dx, [cs:chop_source_len+2]
        ja .return
        jb .end_in_range
        cmp ax, [cs:chop_source_len]
        ja .return
.end_in_range:
        inc si
        cmp si, cx
        jb .validate_zone

        call 0xD0C0:0x084D
        xor dx, dx
        mov dl, [cs:zones_count]
        cmp ax, dx
        jae .slots_ok
        mov word [cs:chop_result], -3
        jmp .return
.slots_ok:
        call 0xD0C0:0x0236
        cmp dx, [cs:chop_required+2]
        jb .no_memory
        ja .resources_ok
        cmp ax, [cs:chop_required]
        jae .resources_ok
.no_memory:
        mov word [cs:chop_result], -2
        jmp .return

.resources_ok:
        ; Read-only preflight passed.  Mute as stock B99A:1732 does before
        ; any naming, allocation or wave-memory work; both exits unmute.
        mov al, 1
        call chop_mute
        mov byte [cs:chop_zone], 0
.create_zone:
        xor bx, bx
        mov bl, [cs:chop_zone]
        shl bx, 1
        shl bx, 1
        add bx, zones_bounds
        mov ax, [cs:bx]
        mov dx, [cs:bx+2]
        mov [cs:chop_start], ax
        mov [cs:chop_start+2], dx
        mov ax, [cs:bx+4]
        mov dx, [cs:bx+6]
        sub ax, [cs:bx]
        sbb dx, [cs:bx+2]
        mov [cs:chop_count], ax
        mov [cs:chop_count+2], dx

        push 1
        push CHOP_CAVE_SEG
        push chop_name
        call 0xC6C2:0x173D
        add sp, 6

        xor ax, ax
        mov al, [cs:chop_source_stereo]
        push ax
        push word [cs:chop_count+2]
        push word [cs:chop_count]
        push CHOP_CAVE_SEG
        push chop_name
        call 0xD0C0:0x0611
        add sp, 10
        or ax, ax
        js .rollback
        mov [cs:chop_dest_index], ax

        ; Fetch both bases after allocation.  D0C0:0611 may compact wave RAM
        ; and move the source before returning.
        mov dx, 0x24
        mul dx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        mov es, ax
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:chop_dest], ax
        mov [cs:chop_dest+2], dx
        mov al, [cs:chop_source_volume]
        mov [es:bx+0x11], al
        mov al, [cs:chop_source_tune]
        mov [es:bx+0x12], al
        ; The allocator already owns exactly chop_count words per plane.  Its
        ; later 441 clamp changes only record +1C; restore the exact logical
        ; length and matching end before exposing the new Sound.
        mov ax, [cs:chop_count]
        mov dx, [cs:chop_count+2]
        mov [es:bx+0x1C], ax
        mov [es:bx+0x1E], dx
        sub ax, 1
        sbb dx, 0
        mov [es:bx+0x18], ax
        mov [es:bx+0x1A], dx
        ; No far call occurs between allocator return and the exact descriptor
        ; correction above.  Record the index now so later failures roll it
        ; back.
        xor bx, bx
        mov bl, [cs:chop_created_count]
        mov ax, [cs:chop_dest_index]
        mov [cs:chop_created+bx], al
        inc byte [cs:chop_created_count]
        call chop_source_record
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        add ax, [cs:chop_start]
        adc dx, [cs:chop_start+2]
        mov [cs:chop_src], ax
        mov [cs:chop_src+2], dx
        call chop_copy_plane

        cmp byte [cs:chop_source_stereo], 0
        je .next_zone
        mov ax, [cs:chop_source_len]
        mov dx, [cs:chop_source_len+2]
        add [cs:chop_src], ax
        adc [cs:chop_src+2], dx
        mov ax, [cs:chop_count]
        mov dx, [cs:chop_count+2]
        add [cs:chop_dest], ax
        adc [cs:chop_dest+2], dx
        call chop_copy_plane

.next_zone:
        inc byte [cs:chop_zone]
        mov al, [cs:chop_zone]
        cmp al, [cs:zones_count]
        jb .create_zone
        mov word [cs:chop_result], 0
        jmp .rollback_done

.rollback:
        mov [cs:chop_result], ax
.rollback_one:
        cmp byte [cs:chop_created_count], 0
        je .rollback_done
        dec byte [cs:chop_created_count]
        xor bx, bx
        mov bl, [cs:chop_created_count]
        xor ax, ax
        mov al, [cs:chop_created+bx]
        push 1
        push 0
        push ax
        call 0xD0C0:0x0B19
        add sp, 6
        jmp .rollback_one
        ; Success and rollback share this tail.  Stock unmutes after its
        ; final 086F on success (B99A:1945) and directly after a failed
        ; allocation (B99A:181F); every post-mute exit passes here.
.rollback_done:
        call 0xD0C0:0x086F
        call chop_refresh_source_base
        mov al, 0
        call chop_mute

.return:
        pop es
        pop ds
        pop di
        pop si
        pop dx
        pop cx
        pop bx
        mov ax, [cs:chop_result]
        ret

.empty:
        mov word [cs:chop_result], CHOP_ERR_EMPTY
        jmp .return

.short:
        mov word [cs:chop_result], CHOP_ERR_SHORT
        jmp .return

; ES:BX = source sound record.  Clobbers AX, DX.
chop_source_record:
        mov ax, [cs:zones_source]
        mov dx, 0x24
        mul dx
        add ax, SND_DIR
        mov bx, ax
        mov ax, SND_SEG
        mov es, ax
        ret

; Keep the map identity and waveform cache coherent if allocation compacted
; the source.  Name, stereo and length are already unchanged and validated.
chop_refresh_source_base:
        call chop_source_record
        mov ax, [es:bx+0x20]
        mov dx, [es:bx+0x22]
        mov [cs:zones_identity+21], ax
        mov [cs:zones_identity+23], dx
        mov [cs:wbase], ax
        mov [cs:wbase+2], dx
        ret

; AL = 1 mutes, 0 unmutes, only while the stock "Mute audio during EDIT SND
; processes" setting is on.  D980:000C writes port 6A and clobbers AL.
chop_mute:
        cmp byte [CHOP_MUTE_EDIT], 0
        je .done
        cbw
        push ax
        call 0xD980:0x000C
        add sp, 2
.done:  ret

chop_copy_plane:
        push word [cs:chop_count+2]
        push word [cs:chop_count]
        push word [cs:chop_dest+2]
        push word [cs:chop_dest]
        push word [cs:chop_src+2]
        push word [cs:chop_src]
        call 0xD0C0:0x0E50
        add sp, 12
        ret

; SI = cave string.  Use the stock save/restore pair and bottom-row cursor;
; one normalized key acknowledges the message, matching the stock modal
; error interaction without assigning a false allocator error number.
chop_show_status:
        push si
        call 0xB1B1:0x004F
        push 0
        push 7
        call 0xB1B1:0x0026
        add sp, 4
        pop si
        push CHOP_CAVE_SEG
        push si
        call 0xB1B1:0x005B
        add sp, 4
        push 0
        call 0xBDE3:0x000E
        add sp, 2
        call 0xB1B1:0x0055
        ret

align 2
chop_do_options:
        dw CHOP_OPT_0, 0x8010
        dw CHOP_OPT_1, 0x8010
        dw CHOP_OPT_2, 0x8010
        dw CHOP_OPT_3, 0x8010
        dw CHOP_OPT_4, 0x8010
        dw CHOP_OPT_5, 0x8010
        dw CHOP_OPT_6, 0x8010
        dw CHOP_OPT_7, 0x8010
        dw CHOP_OPT_8, 0x8010
        dw CHOP_OPT_9, 0x8010
        dw chop_do_text, CHOP_CAVE_SEG
        dd 0
chop_do_text: db "CHOP ZONE", 0
chop_empty_text: db "EMPTY ZONE - ADJUST BOUNDARIES", 0
chop_stale_text: db "REOPEN WAVE VIEW FOR THIS SOUND", 0
chop_short_text: db "ZONE MUST BE AT LEAST 10ms", 0

align 2
chop_result: dw 0
chop_dest_index: dw 0
chop_source_len: dd 0
chop_required: dd 0
chop_start: dd 0
chop_count: dd 0
chop_src: dd 0
chop_dest: dd 0
chop_source_stereo: db 0
chop_source_volume: db 0
chop_source_tune: db 0
chop_zone: db 0
chop_created_count: db 0
chop_selected_record: db 0
chop_created: times ZONE_MAX db 0
chop_name: times 17 db 0
