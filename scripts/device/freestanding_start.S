.global _start
_start:
	mov x0, sp
	bl real_main
	mov x8, #93			/* SYS_exit */
	svc 0
