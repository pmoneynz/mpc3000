; S1a: fast exact 32-bit divide for the note-on layer CFC6:039E
; (notes/performance.md section 9).  Each of the routine's 17 CALLF F800:20FA
; (signed) and CALLF F800:2101 (unsigned) sites is redirected here; nothing
; else in the OS changes.
;
; Entry contract, the same as the BIOS runtime's (F800:2114, bytes
; [0x7A0F7, 0x7A1A5)): far call, operands on the stack
;     [SP+4] dividend low   [SP+6] dividend high
;     [SP+8] divisor low    [SP+10] divisor high
; returns the quotient in DX:AX and pops the 8 operand bytes (RETF 8).
; BX and CX are clobbered (the runtime clobbers them too); SI, DI, BP, DS,
; ES are kept.  No call site reads BX, CX or the flags before writing them.
;
; Fast path: divisor high word 0 and low word non-zero.  The quotient of
; the dividend's magnitude by the 16-bit divisor is formed with two
; DIV r/m16 (the V33's DIVU): high word, then remainder:low word.  The
; second step cannot overflow because the remainder is below the divisor.
; The signed entry negates a negative dividend and negates the quotient
; back (the divisor is positive on this path), which is the runtime's
; truncation toward zero.  Every other divisor, including 0 (where the
; runtime either faults or returns all ones, depending on the dividend),
; tail-jumps to the runtime with the stack exactly as the caller left it.
;
; Uses only the stack: re-entrant across AMX tasks and interrupts.
; The dead divisor-high operand slot holds the high quotient word.

bits 16
org 0

s1a_idiv:                               ; replaces CALLF F800:20FA
        push bp
        mov bp, sp
        mov bx, [bp+10]                 ; divisor low
        cmp word [bp+12], 0
        jne .runtime
        or bx, bx
        jz .runtime
        mov ax, [bp+6]
        mov dx, [bp+8]
        mov cx, dx                      ; CX bit 15: dividend sign = quotient sign
        or dx, dx
        jns .divide
        neg dx
        neg ax
        sbb dx, 0
.divide:
        xchg ax, dx                     ; AX = high, DX = low
        mov [bp+12], dx
        xor dx, dx
        div bx                          ; AX = quotient high, DX = remainder
        xchg ax, [bp+12]                ; AX = low, slot = quotient high
        div bx                          ; AX = quotient low
        mov dx, [bp+12]
        or cx, cx
        jns .done
        neg dx
        neg ax
        sbb dx, 0
.done:
        pop bp
        retf 8
.runtime:
        pop bp
        jmp 0xF800:0x20FA

s1a_udiv:                               ; replaces CALLF F800:2101
        push bp
        mov bp, sp
        mov bx, [bp+10]
        cmp word [bp+12], 0
        jne .runtime
        or bx, bx
        jz .runtime
        mov ax, [bp+8]                  ; AX = high
        xor dx, dx
        div bx
        mov [bp+12], ax                 ; quotient high
        mov ax, [bp+6]                  ; DX = remainder, AX = low
        div bx
        mov dx, [bp+12]
        pop bp
        retf 8
.runtime:
        pop bp
        jmp 0xF800:0x2101
