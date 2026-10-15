//********************************************************//
//     pwrseq_demo.c                                      //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef PWRSEQ_DEMO_C
#define PWRSEQ_DEMO_C

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Global Veriables Declare                               //
//********************************************************//
typedef struct
{
    pwrcell_t pch_p0v85a_en;
    pwrcell_t pch_p1v25a_en;
    pwrcell_t pch_p1v8a_en ;
    pwrcell_t pch_p3v3a_en ;
    pwrcell_t pvnnaon_en   ;
    pwrcell_t pvccio_en    ;
    pwrcell_t pvcc1v8_en   ;
    pwrcell_t rsmrst_n     ;
    pwrcell_t psu_en       ;
    pwrcell_t pvccdd2_en   ;
    pwrcell_t imvp_vr_en   ;
    pwrcell_t pch_pwrok    ;
    struct
    {
        UINT8 t_1us :1;
        UINT8 t_1ms :1;
        UINT8 t_2ms :1;
        UINT8 t_32ms:1;
    }time_isr;
    struct
    {
        UINT8 t_1us :1;
        UINT8 t_1ms :1;
        UINT8 t_2ms :1;
        UINT8 t_32ms:1;
    }time;
}_pwrseq_demo_var;

_pwrseq_demo_var pwrseq_demo_var = {
    .pch_p0v85a_en = { .hi = {.cycle = 5}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pch_p1v25a_en = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pch_p1v8a_en  = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pch_p3v3a_en  = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pvnnaon_en    = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pvccio_en     = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pvcc1v8_en    = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .rsmrst_n      = { .hi = {.cycle = 3}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .psu_en        = { .hi = {.cycle = 4}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pvccdd2_en    = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .imvp_vr_en    = { .hi = {.cycle = 2}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .pch_pwrok     = { .hi = {.cycle = 3}, .lo = {.cycle = 4}, .force = {.polar = 0} }
};

//********************************************************//
// pwrseq_demo_Init()                                     //
//                                                        //
// Description: Variable Initialization                   //
//                                                        //
// Input:     None                                        //
//                                                        //
// Return:    None                                        //
//********************************************************//
void pwrseq_demo_Init(void)
{
    pwrcell_Init(&pwrseq_demo_var.pch_p0v85a_en);
    pwrcell_Init(&pwrseq_demo_var.pch_p1v25a_en);
    pwrcell_Init(&pwrseq_demo_var.pch_p1v8a_en );
    pwrcell_Init(&pwrseq_demo_var.pch_p3v3a_en );
    pwrcell_Init(&pwrseq_demo_var.pvnnaon_en   );
    pwrcell_Init(&pwrseq_demo_var.pvccio_en    );
    pwrcell_Init(&pwrseq_demo_var.pvcc1v8_en   );
    pwrcell_Init(&pwrseq_demo_var.rsmrst_n     );
    pwrcell_Init(&pwrseq_demo_var.psu_en       );
    pwrcell_Init(&pwrseq_demo_var.pvccdd2_en   );
    pwrcell_Init(&pwrseq_demo_var.imvp_vr_en   );
    pwrcell_Init(&pwrseq_demo_var.pch_pwrok    );

    pwrseq_demo_var.time_isr.t_1us  = 0;
    pwrseq_demo_var.time.t_1us      = 0;
    pwrseq_demo_var.time_isr.t_1ms  = 0;
    pwrseq_demo_var.time.t_1ms      = 0;
    pwrseq_demo_var.time_isr.t_2ms  = 0;
    pwrseq_demo_var.time.t_2ms      = 0;
    pwrseq_demo_var.time_isr.t_32ms = 0;
    pwrseq_demo_var.time.t_32ms     = 0;
}

void pwrseq_demo_timer_1us_ISR(void)
{
    pwrseq_demo_var.time_isr.t_1us = 1;
}

void pwrseq_demo_timer_1ms_ISR(void)
{
    pwrseq_demo_var.time_isr.t_1ms = 1;
}

void pwrseq_demo_timer_2ms_ISR(void)
{
    pwrseq_demo_var.time_isr.t_2ms = 1;
}

void pwrseq_demo_timer_32ms_ISR(void)
{
    pwrseq_demo_var.time_isr.t_32ms = 1;
}

void pwrseq_demo_mainLoop(void)
{
UINT32 IRQ = m_oemsys_getIrq();

    if (pwrseq_demo_var.time_isr.t_1us)
    {
        m_oemsys_IrqDis();
        pwrseq_demo_var.time_isr.t_1us = 0;
        m_oemsys_setIrq(IRQ);
        pwrseq_demo_var.time.t_1us = 1;
    }

    if (pwrseq_demo_var.time_isr.t_1ms)
    {
        m_oemsys_IrqDis();
        pwrseq_demo_var.time_isr.t_1ms = 0;
        m_oemsys_setIrq(IRQ);
        pwrseq_demo_var.time.t_1ms = 1;
    }

    if (pwrseq_demo_var.time_isr.t_2ms)
    {
        m_oemsys_IrqDis();
        pwrseq_demo_var.time_isr.t_2ms = 0;
        m_oemsys_setIrq(IRQ);
        pwrseq_demo_var.time.t_2ms = 1;
    }

    if (pwrseq_demo_var.time_isr.t_32ms)
    {
        m_oemsys_IrqDis();
        pwrseq_demo_var.time_isr.t_32ms = 0;
        m_oemsys_setIrq(IRQ);
        pwrseq_demo_var.time.t_32ms = 1;
    }

    // Power cell handlers begin ////////////////////////////////////////////////////
    pwrseq_demo_var.pch_p0v85a_en.hi.condition    = (oemgpio_DI_Get(EKEY) & oemgpio_DI_Get(PRIM_VR_EN));
    pwrseq_demo_var.pch_p0v85a_en.lo.condition    = (!oemgpio_DI_Get(RSMRST_N));
    pwrseq_demo_var.pch_p0v85a_en.force.condition = 0;

    pwrseq_demo_var.pch_p1v25a_en.hi.condition    = (oemgpio_DI_Get(PCH_P0V85A_PG) & oemgpio_DI_Get(PVNNAON_PG));
    pwrseq_demo_var.pch_p1v25a_en.lo.condition    = (pwrseq_demo_var.pch_p0v85a_en.lo.condition & !oemgpio_DI_Get(PCH_P0V85A_PG));
    pwrseq_demo_var.pch_p1v25a_en.force.condition = 0;

    pwrseq_demo_var.pch_p1v8a_en .hi.condition    = (oemgpio_DI_Get(PCH_P1V25A_PG) & oemgpio_DI_Get(PVCCIO_PG));
    pwrseq_demo_var.pch_p1v8a_en .lo.condition    = (pwrseq_demo_var.pch_p1v25a_en.lo.condition & !oemgpio_DI_Get(PCH_P1V25A_PG));
    pwrseq_demo_var.pch_p1v8a_en .force.condition = 0;

    pwrseq_demo_var.pch_p3v3a_en .hi.condition    = (oemgpio_DI_Get(PCH_P1V8A_PG) & oemgpio_DI_Get(PVCC1V8_PG));
    pwrseq_demo_var.pch_p3v3a_en .lo.condition    = (pwrseq_demo_var.pch_p1v8a_en.lo.condition & !oemgpio_DI_Get(PCH_P1V8A_PG));
    pwrseq_demo_var.pch_p3v3a_en .force.condition = 0;

    pwrseq_demo_var.pvnnaon_en   .hi.condition    = (pwrseq_demo_var.pch_p0v85a_en.hi.condition);
    pwrseq_demo_var.pvnnaon_en   .lo.condition    = (!oemgpio_DI_Get(RSMRST_N));
    pwrseq_demo_var.pvnnaon_en   .force.condition = 0;

    pwrseq_demo_var.pvccio_en    .hi.condition    = (pwrseq_demo_var.pch_p1v25a_en.hi.condition);
    pwrseq_demo_var.pvccio_en    .lo.condition    = (pwrseq_demo_var.pvnnaon_en.lo.condition & !oemgpio_DI_Get(PVNNAON_PG));
    pwrseq_demo_var.pvccio_en    .force.condition = 0;

    pwrseq_demo_var.pvcc1v8_en   .hi.condition    = (pwrseq_demo_var.pch_p1v8a_en.hi.condition);
    pwrseq_demo_var.pvcc1v8_en   .lo.condition    = (pwrseq_demo_var.pvccio_en.lo.condition & !oemgpio_DI_Get(PVCCIO_PG));
    pwrseq_demo_var.pvcc1v8_en   .force.condition = 0;

    pwrseq_demo_var.rsmrst_n     .hi.condition    = (pwrseq_demo_var.pch_p0v85a_en.hi.condition & oemgpio_DI_Get(PCH_P0V85A_PG) & oemgpio_DI_Get(PVNNAON_PG) & oemgpio_DI_Get(PCH_P1V25A_PG) & oemgpio_DI_Get(PVCCIO_PG) & oemgpio_DI_Get(PCH_P1V8A_PG) & oemgpio_DI_Get(PVCC1V8_PG) & oemgpio_DI_Get(PCH_P3V3A_PG));
    pwrseq_demo_var.rsmrst_n     .lo.condition    = !((oemgpio_DI_Get(PRIM_VR_EN) & oemgpio_DI_Get(PCH_P0V85A_PG) & oemgpio_DI_Get(PVNNAON_PG) & oemgpio_DI_Get(PCH_P1V25A_PG) & oemgpio_DI_Get(PVCCIO_PG) & oemgpio_DI_Get(PCH_P1V8A_PG) & oemgpio_DI_Get(PVCC1V8_PG) & oemgpio_DI_Get(PCH_P3V3A_PG)));
    pwrseq_demo_var.rsmrst_n     .force.condition = 0;

    pwrseq_demo_var.psu_en       .hi.condition    = (oemgpio_DI_Get(RSMRST_N) & oemgpio_DI_Get(SLPS3_N));
    pwrseq_demo_var.psu_en       .lo.condition    = (!oemgpio_DI_Get(SLPS3_N) & !oemgpio_DI_Get(IMVP_VR_PG));
    pwrseq_demo_var.psu_en       .force.condition = (pwrseq_demo_var.pvccdd2_en.force.condition);

    pwrseq_demo_var.pvccdd2_en   .hi.condition    = (oemgpio_DI_Get(RSMRST_N) & oemgpio_DI_Get(SLPS4_N));
    pwrseq_demo_var.pvccdd2_en   .lo.condition    = (!oemgpio_DI_Get(PCH_PWROK));
    pwrseq_demo_var.pvccdd2_en   .force.condition = (pwrseq_demo_var.pch_pwrok.force.condition & !oemgpio_DI_Get(IMVP_VR_EN) & !oemgpio_DI_Get(SLPS4_N));

    pwrseq_demo_var.imvp_vr_en   .hi.condition    = (oemgpio_DI_Get(RSMRST_N) & oemgpio_DI_Get(PVCCDD2_PG) & oemgpio_DI_Get(SLPS3_N) & oemgpio_DI_Get(PSU_PG));
    pwrseq_demo_var.imvp_vr_en   .lo.condition    = (!oemgpio_DI_Get(SLPS3_N));
    pwrseq_demo_var.imvp_vr_en   .force.condition = 0;

    pwrseq_demo_var.pch_pwrok    .hi.condition    = (pwrseq_demo_var.imvp_vr_en.hi.condition & oemgpio_DI_Get(IMVP_VR_PG));
    pwrseq_demo_var.pch_pwrok    .lo.condition    = (!oemgpio_DI_Get(SLPS3_N));
    pwrseq_demo_var.pch_pwrok    .force.condition = 0;

    pwrcell_handle(&pwrseq_demo_var.pch_p0v85a_en, pwrseq_demo_var.time.t_2ms , pwrseq_demo_var.time.t_1us, PCH_P0V85A_EN);
    pwrcell_handle(&pwrseq_demo_var.pch_p1v25a_en, pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PCH_P1V25A_EN);
    pwrcell_handle(&pwrseq_demo_var.pch_p1v8a_en , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PCH_P1V8A_EN );
    pwrcell_handle(&pwrseq_demo_var.pch_p3v3a_en , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PCH_P3V3A_EN );
    pwrcell_handle(&pwrseq_demo_var.pvnnaon_en   , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PVNNAON_EN   );
    pwrcell_handle(&pwrseq_demo_var.pvccio_en    , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PVCCIO_EN    );
    pwrcell_handle(&pwrseq_demo_var.pvcc1v8_en   , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PVCC1V8_EN   );
    pwrcell_handle(&pwrseq_demo_var.rsmrst_n     , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, RSMRST_N     );
    pwrcell_handle(&pwrseq_demo_var.psu_en       , pwrseq_demo_var.time.t_32ms, pwrseq_demo_var.time.t_1us, PSU_EN       );
    pwrcell_handle(&pwrseq_demo_var.pvccdd2_en   , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PVCCDD2_EN   );
    pwrcell_handle(&pwrseq_demo_var.imvp_vr_en   , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, IMVP_VR_EN   );
    pwrcell_handle(&pwrseq_demo_var.pch_pwrok    , pwrseq_demo_var.time.t_1ms , pwrseq_demo_var.time.t_1us, PCH_PWROK    );
    // Power cell handlers end //////////////////////////////////////////////////////

    pwrseq_demo_var.time.t_1us = 0;
    pwrseq_demo_var.time.t_1ms = 0;
    pwrseq_demo_var.time.t_2ms = 0;
    pwrseq_demo_var.time.t_32ms = 0;
}
#endif  //PWRSEQ_DEMO_C
