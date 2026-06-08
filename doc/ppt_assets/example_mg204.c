//********************************************************//
//     example_mg204.c                                    //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef EXAMPLE_MG204_C
#define EXAMPLE_MG204_C

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Global Veriables Declare                               //
//********************************************************//
typedef struct
{
    pwrcell_t p5v_en     ;
    pwrcell_t p3v3_en    ;
    pwrcell_t p1v8_en    ;
    pwrcell_t p1v1_hub_en;
    struct
    {
        UINT8 t_1us:1;
    }time_isr;
    struct
    {
        UINT8 t_1us:1;
    }time;
}_example_mg204_var;

_example_mg204_var example_mg204_var = {
    .p5v_en      = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .p3v3_en     = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .p1v8_en     = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .p1v1_hub_en = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} }
};

//********************************************************//
// example_mg204_Init()                                   //
//                                                        //
// Description: Variable Initialization                   //
//                                                        //
// Input:     None                                        //
//                                                        //
// Return:    None                                        //
//********************************************************//
void example_mg204_Init(void)
{
    pwrcell_Init(&example_mg204_var.p5v_en     );
    pwrcell_Init(&example_mg204_var.p3v3_en    );
    pwrcell_Init(&example_mg204_var.p1v8_en    );
    pwrcell_Init(&example_mg204_var.p1v1_hub_en);

    example_mg204_var.time_isr.t_1us = 0;
    example_mg204_var.time.t_1us     = 0;
}

void example_mg204_timer_1us_ISR(void)
{
    example_mg204_var.time_isr.t_1us = 1;
}

void example_mg204_mainLoop(void)
{
UINT32 IRQ = m_oemsys_getIrq();

    if (example_mg204_var.time_isr.t_1us)
    {
        m_oemsys_IrqDis();
        example_mg204_var.time_isr.t_1us = 0;
        m_oemsys_setIrq(IRQ);
        example_mg204_var.time.t_1us = 1;
    }

    // Power cell handlers begin ////////////////////////////////////////////////////
    example_mg204_var.p5v_en     .hi.condition    = (oemgpio_DI_Get(PS_PWOK));
    example_mg204_var.p5v_en     .lo.condition    = (!oemgpio_DI_Get(PS_PWOK));
    example_mg204_var.p5v_en     .force.condition = 0;

    example_mg204_var.p3v3_en    .hi.condition    = (oemgpio_DI_Get(P5V_PG));
    example_mg204_var.p3v3_en    .lo.condition    = (!oemgpio_DI_Get(P5V_PG));
    example_mg204_var.p3v3_en    .force.condition = 0;

    example_mg204_var.p1v8_en    .hi.condition    = (oemgpio_DI_Get(P3V3_PG));
    example_mg204_var.p1v8_en    .lo.condition    = (!oemgpio_DI_Get(P3V3_PG));
    example_mg204_var.p1v8_en    .force.condition = 0;

    example_mg204_var.p1v1_hub_en.hi.condition    = (oemgpio_DI_Get(P1V8_PG));
    example_mg204_var.p1v1_hub_en.lo.condition    = (!oemgpio_DI_Get(P1V8_PG));
    example_mg204_var.p1v1_hub_en.force.condition = 0;

    pwrcell_handle(&example_mg204_var.p5v_en     , example_mg204_var.time.t_1us, 1, P5V_EN     );
    pwrcell_handle(&example_mg204_var.p3v3_en    , example_mg204_var.time.t_1us, 1, P3V3_EN    );
    pwrcell_handle(&example_mg204_var.p1v8_en    , example_mg204_var.time.t_1us, 1, P1V8_EN    );
    pwrcell_handle(&example_mg204_var.p1v1_hub_en, example_mg204_var.time.t_1us, 1, P1V1_HUB_EN);
    // Power cell handlers end //////////////////////////////////////////////////////

    example_mg204_var.time.t_1us = 0;
}
#endif  //EXAMPLE_MG204_C
