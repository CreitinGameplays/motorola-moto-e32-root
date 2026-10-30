/*
 * Runs at the arm64 Image entry point, before head.S, with the MMU still off:
 * every store below is a physical store, so no page tables are needed.
 *
 * It paints a white band (256000 bytes = the top ~40 rows of 1600x720x32)
 * at the bootloader's framebuffer base (lcd_base=9e000000 from /proc/cmdline)
 * and then branches to the real stext.  The Image header it overwrites has
 * already been parsed by the bootloader, which jumps to the image start.
 *
 * "Did the bootloader enter our Image at all?" becomes a yes/no the operator
 * can see on the screen, without any reset, RAM retention or console.
 *
 * Exactly 16 instructions: 15 here, then the original `b stext` word is
 * appended by patch_entry_paint.py (it is PC-relative from offset 0, so the
 * original first word of the Image is already the right branch).
 */
	.section .text
	.global entry_paint
entry_paint:
	mov	x19, x0				/* preserve the boot args */
	mov	x20, x1
	mov	x21, x2
	mov	x22, x3
	movz	x9, #0x9e00, lsl #16		/* x9 = 0x9e000000 (lcd_base) */
	movn	x11, #0				/* x11 = 0xffff...ff (white) */
	movz	x10, #16000			/* 16000*16 = 256000 bytes */
1:	stp	x11, x11, [x9], #16
	subs	x10, x10, #1
	b.ne	1b
	mov	x0, x19
	mov	x1, x20
	mov	x2, x21
	mov	x3, x22
	/* .word <original b stext>, appended by the host tool */