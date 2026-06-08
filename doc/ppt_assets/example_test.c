//********************************************************//
//     example_test.c                                     //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef EXAMPLE_TEST_C
#define EXAMPLE_TEST_C

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Global Veriables Declare                               //
//********************************************************//
typedef struct
{
    pwrcell_t out1;
    struct
    {
        UINT8 t_1us:1;
    }time_isr;
    struct
    {
        UINT8 t_1us:1;
    }time;
}_example_test_var;

_example_test_var example_test_var = {
    .out1 = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} }
};

//********************************************************//
// example_test_Init()                                    //
//                                                        //
// Description: Variable Initialization                   //
//                                                        //
// Input:     None                                        //
//                                                        //
// Return:    None                                        //
//********************************************************//
void example_test_Init(void)
{
    pwrcell_Init(&example_test_var.out1);

    example_test_var.time_isr.t_1us = 0;
    example_test_var.time.t_1us     = 0;
}

void example_test_timer_1us_ISR(void)
{
    example_test_var.time_isr.t_1us = 1;
}

void example_test_mainLoop(void)
{
UINT32 IRQ = m_oemsys_getIrq();

    if (example_test_var.time_isr.t_1us)
    {
        m_oemsys_IrqDis();
        example_test_var.time_isr.t_1us = 0;
        m_oemsys_setIrq(IRQ);
        example_test_var.time.t_1us = 1;
    }

    // Power cell handlers begin ////////////////////////////////////////////////////
    example_test_var.out1.hi.condition    = (oemgpio_DI_Get(IN1));
    example_test_var.out1.lo.condition    = (!oemgpio_DI_Get(IN1));
    example_test_var.out1.force.condition = 0;

    pwrcell_handle(&example_test_var.out1, example_test_var.time.t_1us, 1, OUT1);
    // Power cell handlers end //////////////////////////////////////////////////////

    example_test_var.time.t_1us = 0;
}
#endif  //EXAMPLE_TEST_C
