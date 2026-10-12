; OS 3.16 profile (M3K316.SYS).  Selected by mods/profile.inc with -DPROFILE_316.
; Addresses are relative to the 3.16 load image: seg:off as stored in the
; file, image offset = seg*16+off; the EPROM loader adds the load segment L
; (6900h on 3.12/3.50, 7000h on 3.08/3.11) to every relocated segment word.
; DS offsets are 3.16 DGROUP (relative segment 609Ch).  Each comment gives the
; generic Vailixi 3.50 address the symbol is named after, then what it is.
; Evidence: notes/port_316.md (orchestrator cross-checks of seven mapping
; packages, 2026-10-05).
;
; Every segment word in the 3.16 cave carries an MZ relocation.  RELOC_PREV
; defines the global label __reloc_<n> at the segment word just emitted; the
; builder (mods/build_wave316.py) collects every __reloc_* symbol.

%assign RELOC_N 0

%macro RELOC_PREV 0
%assign RELOC_N RELOC_N+1
__reloc_%[RELOC_N] equ $-2
%endmacro

%macro FCALL 1
        call %1
        RELOC_PREV
%endmacro

%macro FJMP 1
        jmp %1
        RELOC_PREV
%endmacro

; ---------------------------------------------------------------- segments

CAVE_HOME  equ 0x7E00           ; cave home paragraph, above 3.16's extent 7DFBh
SND_SEG    equ 0x539D           ; A2AE: sound segment (buffer 0000, records 4800)
DGROUP_SEG equ 0x609C           ; 8010: DGROUP, DS in the hooked routines
CAVE_SEG   equ CAVE_HOME        ; F07D: this cave at its home
PLAYER_SEG equ 0x20ED           ; CFC6: stock sound player module

; ---------------------------------------------------------------- shared

SND_DIR    equ 0x4800           ; first sound record in SND_SEG, 24h bytes each
FB         equ 0x1579           ; 1591: LCD framebuffer, 30 bytes x 64 rows
KEY_REPEAT equ 0xD387           ; D69A: normalized-key repeat count (2D0B:001D)
%define T_B1B1_004F 0x0427:0x0059       ; save the text shadow (INT 43 AX=5)
%define T_B1B1_0055 0x0427:0x005F       ; restore that shadow (INT 43 AX=6)
%define T_BDE3_000E 0x0F6B:0x0009       ; next key after the global filter
%define T_C4C8_0409 0x1650:0x03FD       ; clear, text mode, INT 43 AX=1
%define T_C4C8_0F0D 0x1650:0x0F01       ; blit FB
%define T_C4C8_0F5F 0x1650:0x0F53       ; graphics mode + blit FB
%define T_B99A_1595 0x0B72:0x1209       ; leave Edit Sound for the menu
%define T_B99A_16BB 0x0B72:0x132B       ; redraw the 17 Edit Sound fields

; ---------------------------------------------------------------- view (wave.asm)

BUF_W      equ 0x2400           ; Best st's read buffer SND_SEG:0000, words
BUSY       equ 0x9444           ; 9757: transfer busy counter (stock 3.16 Edit
                                ; Sound does not wrap its reads; kept, harmless)
MODE       equ 0xD4B8           ; D7CB: mode, 'L' = Program/Sounds
OPTION     equ 0xD4B7           ; D7CA: option, 6 = Edit Sound
ZONE_ST    equ 0xE45A           ; EDBB: zone start dword (Edit Sound field)
ZONE_EN    equ 0xE456           ; EDB7: zone end dword
%define T_B060_0428 0x02D7:0x0422       ; field editor key loop: stock Help
%define T_B060_0459 0x02D7:0x0453       ; field editor key loop: other keys
%define T_B060_06E2 0x02D7:0x06DC       ; field editor key loop: return key SI
%define T_B99A_0AF3 0x0B72:0x0AF8       ; Edit Sound Do dispatch (key 75h)
%define T_CF92_000C 0x20BA:0x0002       ; wave transfer (dst, wave, count, dir)

; ---------------------------------------------------------------- numeric entry (wave_numeric.inc)

NUM_EDITING equ 0x7A62          ; 7D74: 0 while an entry buffer is active
%define T_B060_006B 0x02D7:0x0065       ; select a live Edit Sound field record
%define T_B060_021C 0x02D7:0x0216       ; initialize its parser and display
%define T_B060_0715 0x02D7:0x070F       ; commit the active entry buffer
%define T_B1B1_0008 0x0427:0x0012       ; cursor shape (0 hides)
%define T_B31B_0007 0x058F:0x000B       ; numeric field editor (key, flags)
%define T_B99A_2619 0x0B72:0x2124       ; component triple (far) -> frames
%define T_B99A_266D 0x0B72:0x2178       ; frames -> component triple (far)

; ---------------------------------------------------------------- audition (wave_playback.inc)

PLAYER_CE9_RET equ 0x0D76               ; 0D70: CEF's return from the player 03A4
%define T_CFC6_0CE9 0x20ED:0x0CEF       ; start the Sound at index (word)
%define T_CFC6_0D75 0x20ED:0x0D7B       ; any voice pending (AX=1), else 0
%define T_CFC6_0D93 0x20ED:0x0D99       ; stop all 32 channels (Ply/Stp stop)
%define T_CFC6_06A3 0x20ED:0x06A9       ; player after the 30 ms SUB/SBB at 06A3
%define T_CFC6_089E 0x20ED:0x08A4       ; player after the tick MOV/CMP at 089D
%define T_CFC6_0B21 0x20ED:0x0B27       ; player epilogue: no voice started

; ---------------------------------------------------------------- zones (wave_zones.inc)

KEY_QUEUE  equ 0x12A4           ; 12BC: AMX key queue, byte queue of 8
LIST_SELECTION equ 0xE0F7       ; E40A: sorted Sound list position, word
%define T_FB00_06B9 0x47BF:0x06B3       ; AMX queue push-front (3.16's own AMX)
%define T_B99A_0009 0x0B72:0x0013       ; Edit Sound after its replaced prologue
%define T_B99A_006B 0x0B72:0x0070       ; Edit Sound after the sorted-list seam
%define T_B99A_04E3 0x0B72:0x04E8       ; field 0 handler, sound present
%define T_B99A_082E 0x0B72:0x0833       ; Edit Sound input loop

; ---------------------------------------------------------------- CHOP (wave_chop.inc)

; 3.16 has 8 stock Do options, no "safe lock" and no Edit Sound mute
; (CHOP_SAFE_LOCK / CHOP_MUTE_EDIT stay undefined), no ZONE%03d naming
; (CHOP_OWN_NAMES), and no allocation rebuild at Edit Sound entry
; (CHOP_REBUILD_FIRST).
CHOP_SEQ_STATE equ 0xA49B       ; A7AE: transport state (HYPOTHESIS); unused here
CHOP_DO        equ 0xE454       ; EDB5: Do choice index
CHOP_DO_LABEL  equ 0x33F3       ; 3781: "Do:"
%define CHOP_STOCK_OPTIONS 8        ; COPY ZONE->TEMP .. REVERSE ZONE
CHOP_OPT_0     equ 0x32C6       ; COPY ZONE-> TEMP
CHOP_OPT_1     equ 0x32D7       ; INS TMP-> ZON ST
CHOP_OPT_2     equ 0x32E8       ; INS TMP-> ZN END
CHOP_OPT_3     equ 0x32F9       ; DELETE ZONE
CHOP_OPT_4     equ 0x3305       ; DEL BEFR SOFT ST
CHOP_OPT_5     equ 0x3316       ; DEL AFTR SFT END
CHOP_OPT_6     equ 0x3327       ; SILENCE ZONE
CHOP_OPT_7     equ 0x3334       ; REVERSE ZONE
%define CHOP_OWN_NAMES
%define CHOP_REBUILD_FIRST
%define T_B1B1_0026 0x0427:0x0030       ; cursor position (INT 43 AX=3)
%define T_B1B1_005B 0x0427:0x0065       ; put string (far) at the cursor
%define T_B354_01C6 0x05C8:0x01CA       ; add a choice field record
%define T_B3C7_0007 0x063B:0x000B       ; stock error box (error number)
%define T_B99A_048F 0x0B72:0x0494       ; Edit Sound after the Do field
%define T_B99A_0B0D 0x0B72:0x0B12       ; stock Do jump table (BX = 0..7)
%define T_B99A_27F2 0x0B72:0x22FD       ; rebuild the sorted Sound list
%define T_D0C0_0236 0x21E7:0x023C       ; free wave words, DX:AX
%define T_D0C0_0611 0x21E7:0x0617       ; allocate Sound (name, length, stereo)
%define T_D0C0_084D 0x21E7:0x0853       ; free record count
%define T_D0C0_086F 0x21E7:0x0875       ; rebuild allocation state
%define T_D0C0_0B19 0x21E7:0x0B1F       ; free Sound (index, mode, flag)
%define T_D0C0_0B1F 0x21E7:0x0B25       ; free Sound after its replaced prologue
%define T_D0C0_0D17 0x21E7:0x0D1D       ; find Sound by name: index, or -4
%define T_D0C0_0E50 0x21E7:0x0E56       ; copy wave words (src, dest, count)

; ---------------------------------------------------------------- mute storage (mute_storage.inc)

%define T_C887_19FB 0x19F9:0x1A06       ; after the program-record copy
%define T_CEE6_0086 0x200D:0x008C       ; close (handle)
%define T_CF0C_0073 0x2033:0x0079       ; fixed-size read (buffer, handle, n)
%define T_CF0C_0096 0x2033:0x009C       ; fixed-size write (buffer, handle, n)
%define T_CF37_04B3 0x207C:0x02D9       ; program init after its prologue

; ---------------------------------------------------------------- mute voice (mute_voice.inc)

MUTE_CURRENT_PROGRAM equ 0xE2FB ; E60E: selected program 0..23
%define T_CF37_0002 0x205E:0x0008       ; voice allocator
%define T_CFC6_0007 0x20ED:0x000D       ; shared note-on engine (event far)
%define T_D1F7_0126 0x2325:0x011E       ; reserve AMX resource 1 (allocation lock)
%define T_D21F_0008 0x234D:0x0000       ; one-channel stop (channel)
%define T_D9F2_003D 0x301D:0x003B       ; first pad slot mapped to a note
MUTE_PAD_MODE  equ 0x8063       ; 8375: non-zero: pad slot notes come from MUTE_PAD_NOTES (301D:000A)
MUTE_PAD_NOTES equ 0x8064       ; 8376: 64 pad slot notes used while MUTE_PAD_MODE is set
%define T_F800_20FA 0x0009:0x20F6       ; signed 32-bit divide: 3.16's linked copy of the BIOS runtime (image 0x2186)
%define T_F800_2101 0x0009:0x20FD       ; unsigned 32-bit divide (same copy)

; ---------------------------------------------------------------- mute UI (mute_ui.inc)

MUTE_PROGRAM   equ 0xE2FB       ; E60E: selected program 0..23
MUTE_RECORD    equ 0xE2E6       ; E5F9: far pointer to its program record
MUTE_PAD       equ 0xD399       ; D6AC: current pad slot (pad + bank)
MUTE_NOTE      equ 0xD39A       ; D6AD: note of the last pad event
MUTE_NOTE_MIDI equ 0xD39B       ; D6AE: note of the last MIDI event
%define T_C887_006B 0x19F9:0x0071       ; stock menu dispatch continuation
%define T_C887_00F1 0x19F9:0x00FC       ; menu return continuation (DL)
%define T_CA45_0008 0x19F9:0x1BF3       ; select program (index)
%define T_D9F2_000C 0x301D:0x000A       ; effective pad slot -> note

; ---------------------------------------------------------------- start-up (entry316.inc)

POOL_INIT_IMM equ 0x48535       ; image offset of 3.16's MOV BX,6FFFh pool end
