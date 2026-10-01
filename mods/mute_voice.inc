; MUTE GROUPS note-on and voice-allocation backend.
;
; Hook sites (both generic Vailixi 3.50 and the 2026-10-01 capture):
;   linear 4FBD3, CFB3:00A3  CALLF CFC6:0007 -> mute_note_on_wrapper
;   linear 507AC, CFC6:0B4C  CALLF CF37:0002 -> mute_voice_alloc_wrapper
;
; Both wrappers are far cdecl routines.  The storage API is in the same
; F07D cave and is called near:
;   mute_get_enabled: AL=program 0..23 -> AL=0/1
;   mute_get_group:   AL=program, BL=canonical pad 0..63 -> AL=0..4
; These APIs preserve SI, DI, BP, and DS.

%ifdef WAVE_CAPTURE_20261001
MUTE_CURRENT_PROGRAM equ 0xE60C
%else
MUTE_CURRENT_PROGRAM equ 0xE60E
%endif

MUTE_PROGRAM_COUNT equ 24
MUTE_PAD_COUNT     equ 64
MUTE_VOICE_COUNT   equ 32

; Wrap the shared note-on engine so every layer and stereo plane inherits
; one canonical (program, pad) context.  The incoming group is also cached
; for this trigger, while candidate groups are looked up during each choke
; scan so UI edits apply to voices that are already sounding.  Saving the old
; context on the stack makes a nested note-on restore the outer context.
mute_note_on_wrapper:
        push bp
        mov bp, sp
        push word [cs:mute_context_valid] ; valid + program
        push word [cs:mute_context_pad]   ; pad + group
        mov byte [cs:mute_context_valid], 0
        mov byte [cs:mute_context_group], 0

        mov al, [MUTE_CURRENT_PROGRAM]
        cmp al, MUTE_PROGRAM_COUNT
        jae .forward
        mov [cs:mute_context_program], al
        les bx, [bp+6]                   ; far pointer to the stock event
        mov al, [es:bx+2]                ; MIDI note, 23h..62h for pads
        xor ah, ah
        push ax
        call 0xD9F2:0x003D               ; first pad slot mapped to note
        add sp, 2
        cmp ax, MUTE_PAD_COUNT
        jae .forward
        mov [cs:mute_context_pad], al
        mov byte [cs:mute_context_valid], 1

        mov al, [cs:mute_context_program]
        call mute_get_enabled
        or al, al
        jz .forward                      ; still tag mapped voices while disabled
        mov bl, [cs:mute_context_pad]
        mov al, [cs:mute_context_program]
        call mute_get_group
        cmp al, 1
        jb .forward
        cmp al, 4
        ja .forward
        mov [cs:mute_context_group], al

.forward:
        push word [bp+8]                 ; event segment
        push word [bp+6]                 ; event offset
        call 0xCFC6:0x0007
        add sp, 4
        pop word [cs:mute_context_pad]
        pop word [cs:mute_context_valid]
        leave
        retf

; Wrap the sole stock voice allocator call.  Before each layer/plane is
; allocated, stop every tagged channel belonging to another pad in the same
; program whose current group matches the incoming group.  Same-pad channels
; are left to the stock retrigger, Poly, and Cutoff machinery.  Every mapped
; allocation is tagged even while MUTE GROUPS is disabled or its pad is Off;
; this lets a later enable/group edit act on voices that are still sounding.
; An unmapped/audition allocation clears any older tag on the returned channel.
mute_voice_alloc_wrapper:
        push bp
        mov bp, sp
        push si
        push di

        cmp byte [cs:mute_context_group], 1
        jb .allocate
        xor di, di
.scan:
        mov al, [cs:mute_context_program]
        inc al                           ; stored program tag is 1..24
        cmp byte [cs:mute_voice_program+di], al
        jne .next
        mov al, [cs:mute_voice_pad+di]
        cmp al, [cs:mute_context_pad]
        je .next
        mov bl, al                       ; candidate's current group, not old group
        mov al, [cs:mute_context_program]
        call mute_get_group
        cmp al, [cs:mute_context_group]
        jne .next
        mov byte [cs:mute_voice_program+di], 0
        mov byte [cs:mute_voice_pad+di], 0
        push di
        call 0xD21F:0x0008              ; stock one-channel stop primitive
        add sp, 2
.next:
        inc di
        cmp di, MUTE_VOICE_COUNT
        jb .scan

.allocate:
        push word [bp+0x0E]             ; channel excluded from voice steal
        push word [bp+0x0C]             ; Cutoff note 2
        push word [bp+0x0A]             ; Cutoff note 1
        push word [bp+0x08]             ; owner/source note
        push word [bp+0x06]             ; Poly enum
        call 0xCF37:0x0002
        add sp, 10

        cmp ax, MUTE_VOICE_COUNT
        jae .done                       ; defensive: stock normally returns 0..31
        mov bx, ax
        cmp byte [cs:mute_context_valid], 1
        jne .clear
        mov dl, [cs:mute_context_program]
        inc dl                           ; program tag 1..24; zero is invalid
        mov [cs:mute_voice_program+bx], dl
        mov dl, [cs:mute_context_pad]
        mov [cs:mute_voice_pad+bx], dl
        jmp .done
.clear:
        mov byte [cs:mute_voice_program+bx], 0
        mov byte [cs:mute_voice_pad+bx], 0
.done:
        pop di
        pop si
        leave
        retf

; Invalidate voice tags before a program record is initialized or a copy
; overwrites the destination.  Sounding channels are not stopped; they simply
; cease to participate in later mute-group decisions for the old record.
; Near ABI: AL=program 0..23; preserves SI, DI, BP, and DS.
mute_forget_program:
        cmp al, MUTE_PROGRAM_COUNT
        jae .return
        inc al                           ; stored program tag is 1..24
        mov dl, al
        xor bx, bx
.loop:
        cmp byte [cs:mute_voice_program+bx], dl
        jne .keep
        mov byte [cs:mute_voice_program+bx], 0
        mov byte [cs:mute_voice_pad+bx], 0
.keep:
        inc bx
        cmp bx, MUTE_VOICE_COUNT
        jb .loop
.return:
        ret

; A zero program tag is invalid.  Nonzero values encode program+1, and the
; parallel byte records the canonical pad.  Group membership stays live in
; the storage table and is deliberately not copied into these voice tags.
mute_context_valid:   db 0
mute_context_program: db 0
mute_context_pad:     db 0
mute_context_group:   db 0
mute_voice_program:   times MUTE_VOICE_COUNT db 0
mute_voice_pad:       times MUTE_VOICE_COUNT db 0
