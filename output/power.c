//********************************************************//
//     power.c                                            //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef POWER_C
#define POWER_C

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
        UINT8 t_1us:1;
        UINT8 t_1ms:1;
        UINT8 t_2ms:1;
        UINT8 t_32ms:1;
    }time_isr;
    struct
    {
        UINT8 t_1us:1;
        UINT8 t_1ms:1;
        UINT8 t_2ms:1;
        UINT8 t_32ms:1;
    }time;
}_power_var;

_power_var power_var = {
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
// power_Init()                                           //
//                                                        //
// Description: Variable Initialization                   //
//                                                        //
// Input:     None                                        //
//                                                        //
// Return:    None                                        //
//********************************************************//
void power_Init(void)
{
    pwrcell_Init(&power_var.pch_p0v85a_en);
    pwrcell_Init(&power_var.pch_p1v25a_en);
    pwrcell_Init(&power_var.pch_p1v8a_en );
    pwrcell_Init(&power_var.pch_p3v3a_en );
    pwrcell_Init(&power_var.pvnnaon_en   );
    pwrcell_Init(&power_var.pvccio_en    );
    pwrcell_Init(&power_var.pvcc1v8_en   );
    pwrcell_Init(&power_var.rsmrst_n     );
    pwrcell_Init(&power_var.psu_en       );
    pwrcell_Init(&power_var.pvccdd2_en   );
    pwrcell_Init(&power_var.imvp_vr_en   );
    pwrcell_Init(&power_var.pch_pwrok    );

    power_var.time_isr.t_1us  = 0;
    power_var.time.t_1us      = 0;
    power_var.time_isr.t_1ms  = 0;
    power_var.time.t_1ms      = 0;
    power_var.time_isr.t_2ms  = 0;
    power_var.time.t_2ms      = 0;
    power_var.time_isr.t_32ms = 0;
    power_var.time.t_32ms     = 0;
}

void power_timer_1us_ISR(void)
{
    power_var.time_isr.t_1us = 1;
}

void power_timer_1ms_ISR(void)
{
    power_var.time_isr.t_1ms = 1;
}

void power_timer_2ms_ISR(void)
{
    power_var.time_isr.t_2ms = 1;
}

void power_timer_32ms_ISR(void)
{
    power_var.time_isr.t_32ms = 1;
}

void power_mainLoop(void)
{
UINT32 IRQ = m_oemsys_getIrq();

    if (power_var.time_isr.t_1us)
    {
        m_oemsys_IrqDis();
        power_var.time_isr.t_1us = 0;
        m_oemsys_setIrq(IRQ);
        power_var.time.t_1us = 1;
    }

    if (power_var.time_isr.t_1ms)
    {
        m_oemsys_IrqDis();
        power_var.time_isr.t_1ms = 0;
        m_oemsys_setIrq(IRQ);
        power_var.time.t_1ms = 1;
    }

    if (power_var.time_isr.t_2ms)
    {
        m_oemsys_IrqDis();
        power_var.time_isr.t_2ms = 0;
        m_oemsys_setIrq(IRQ);
        power_var.time.t_2ms = 1;
    }

    if (power_var.time_isr.t_32ms)
    {
        m_oemsys_IrqDis();
        power_var.time_isr.t_32ms = 0;
        m_oemsys_setIrq(IRQ);
        power_var.time.t_32ms = 1;
    }

    // Power cell handlers begin ////////////////////////////////////////////////////
    power_var.pch_p0v85a_en.hi.condition    = (oemgpio_DI_Get(EKEY) && oemgpio_DI_Get(PRIM_VR_EN));
    power_var.pch_p0v85a_en.lo.condition    = (!oemgpio_DI_Get(RSMRST_N));
    power_var.pch_p0v85a_en.force.condition = 0;

    power_var.pch_p1v25a_en.hi.condition    = (oemgpio_DI_Get(PCH_P0V85A_PG) && oemgpio_DI_Get(PVNNAON_PG));
    power_var.pch_p1v25a_en.lo.condition    = (power_var.pch_p0v85a_en.lo.condition && !oemgpio_DI_Get(PCH_P0V85A_PG));
    power_var.pch_p1v25a_en.force.condition = 0;

    power_var.pch_p1v8a_en .hi.condition    = (oemgpio_DI_Get(PCH_P1V25A_PG) && oemgpio_DI_Get(PVCCIO_PG));
    power_var.pch_p1v8a_en .lo.condition    = (power_var.pch_p1v25a_en.lo.condition && !oemgpio_DI_Get(PCH_P1V25A_PG));
    power_var.pch_p1v8a_en .force.condition = 0;

    power_var.pch_p3v3a_en .hi.condition    = (oemgpio_DI_Get(PCH_P1V8A_PG) && oemgpio_DI_Get(PVCC1V8_PG));
    power_var.pch_p3v3a_en .lo.condition    = (power_var.pch_p1v8a_en.lo.condition && !oemgpio_DI_Get(PCH_P1V8A_PG));
    power_var.pch_p3v3a_en .force.condition = 0;

    power_var.pvnnaon_en   .hi.condition    = (power_var.pch_p0v85a_en.hi.condition);
    power_var.pvnnaon_en   .lo.condition    = (!oemgpio_DI_Get(RSMRST_N));
    power_var.pvnnaon_en   .force.condition = 0;

    power_var.pvccio_en    .hi.condition    = (power_var.pch_p1v25a_en.hi.condition);
    power_var.pvccio_en    .lo.condition    = (power_var.pvnnaon_en.lo.condition && !oemgpio_DI_Get(PVNNAON_PG));
    power_var.pvccio_en    .force.condition = 0;

    power_var.pvcc1v8_en   .hi.condition    = (power_var.pch_p1v8a_en.hi.condition);
    power_var.pvcc1v8_en   .lo.condition    = (power_var.pvccio_en.lo.condition && !oemgpio_DI_Get(PVCCIO_PG));
    power_var.pvcc1v8_en   .force.condition = 0;

    power_var.rsmrst_n     .hi.condition    = (power_var.pch_p0v85a_en.hi.condition && oemgpio_DI_Get(PCH_P0V85A_PG) && oemgpio_DI_Get(PVNNAON_PG) && oemgpio_DI_Get(PCH_P1V25A_PG) && oemgpio_DI_Get(PVCCIO_PG) && oemgpio_DI_Get(PCH_P1V8A_PG) && oemgpio_DI_Get(PVCC1V8_PG) && oemgpio_DI_Get(PCH_P3V3A_PG));
    power_var.rsmrst_n     .lo.condition    = !(oemgpio_DI_Get(PRIM_VR_EN) && oemgpio_DI_Get(PCH_P0V85A_PG) && oemgpio_DI_Get(PVNNAON_PG) && oemgpio_DI_Get(PCH_P1V25A_PG) && oemgpio_DI_Get(PVCCIO_PG) && oemgpio_DI_Get(PCH_P1V8A_PG) && oemgpio_DI_Get(PVCC1V8_PG) && oemgpio_DI_Get(PCH_P3V3A_PG));
    power_var.rsmrst_n     .force.condition = 0;

    power_var.psu_en       .hi.condition    = (oemgpio_DI_Get(RSMRST_N) && oemgpio_DI_Get(SLPS3_N));
    power_var.psu_en       .lo.condition    = (!oemgpio_DI_Get(SLPS3_N) && !oemgpio_DI_Get(IMVP_VR_PG));
    power_var.psu_en       .force.condition = (power_var.pvccdd2_en.force.condition);

    power_var.pvccdd2_en   .hi.condition    = (oemgpio_DI_Get(RSMRST_N) && oemgpio_DI_Get(SLPS4_N));
    power_var.pvccdd2_en   .lo.condition    = (!oemgpio_DI_Get(PCH_PWROK));
    power_var.pvccdd2_en   .force.condition = (power_var.pch_pwrok.force.condition && !oemgpio_DI_Get(IMVP_VR_EN) && !oemgpio_DI_Get(SLPS4_N));

    power_var.imvp_vr_en   .hi.condition    = (oemgpio_DI_Get(RSMRST_N) && oemgpio_DI_Get(PVCCDD2_PG) && oemgpio_DI_Get(SLPS3_N) && oemgpio_DI_Get(PSU_PG));
    power_var.imvp_vr_en   .lo.condition    = (!oemgpio_DI_Get(SLPS3_N));
    power_var.imvp_vr_en   .force.condition = 0;

    power_var.pch_pwrok    .hi.condition    = (power_var.imvp_vr_en.hi.condition && oemgpio_DI_Get(IMVP_VR_PG));
    power_var.pch_pwrok    .lo.condition    = (!oemgpio_DI_Get(SLPS3_N));
    power_var.pch_pwrok    .force.condition = 0;

    pwrcell_handle(&power_var.pch_p0v85a_en, power_var.time.t_2ms , power_var.time.t_1us, PCH_P0V85A_EN);
    pwrcell_handle(&power_var.pch_p1v25a_en, power_var.time.t_1ms , power_var.time.t_1us, PCH_P1V25A_EN);
    pwrcell_handle(&power_var.pch_p1v8a_en , power_var.time.t_1ms , power_var.time.t_1us, PCH_P1V8A_EN );
    pwrcell_handle(&power_var.pch_p3v3a_en , power_var.time.t_1ms , power_var.time.t_1us, PCH_P3V3A_EN );
    pwrcell_handle(&power_var.pvnnaon_en   , power_var.time.t_1ms , power_var.time.t_1us, PVNNAON_EN   );
    pwrcell_handle(&power_var.pvccio_en    , power_var.time.t_1ms , power_var.time.t_1us, PVCCIO_EN    );
    pwrcell_handle(&power_var.pvcc1v8_en   , power_var.time.t_1ms , power_var.time.t_1us, PVCC1V8_EN   );
    pwrcell_handle(&power_var.rsmrst_n     , power_var.time.t_1ms , power_var.time.t_1us, RSMRST_N     );
    pwrcell_handle(&power_var.psu_en       , power_var.time.t_32ms, power_var.time.t_1us, PSU_EN       );
    pwrcell_handle(&power_var.pvccdd2_en   , power_var.time.t_1ms , power_var.time.t_1us, PVCCDD2_EN   );
    pwrcell_handle(&power_var.imvp_vr_en   , power_var.time.t_1ms , power_var.time.t_1us, IMVP_VR_EN   );
    pwrcell_handle(&power_var.pch_pwrok    , power_var.time.t_1ms , power_var.time.t_1us, PCH_PWROK    );
    // Power cell handlers end //////////////////////////////////////////////////////

    power_var.time.t_1us = 0;
    power_var.time.t_1ms = 0;
    power_var.time.t_2ms = 0;
    power_var.time.t_32ms = 0;
}
#endif  //POWER_C
