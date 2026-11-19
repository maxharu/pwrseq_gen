//********************************************************//
//     pwrseq_vec.c                                       //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef PWRSEQ_VEC_C
#define PWRSEQ_VEC_C

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Global Veriables Declare                               //
//********************************************************//
typedef struct
{
    pwrcell_t vout[2];
    struct
    {
        UINT8 t_1us:1;
    }time_isr;
    struct
    {
        UINT8 t_1us:1;
    }time;
}_pwrseq_vec_var;

_pwrseq_vec_var pwrseq_vec_var = {
    .vout[0] = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} },
    .vout[1] = { .hi = {.cycle = 8}, .lo = {.cycle = 4}, .force = {.polar = 0} }
};

//********************************************************//
// pwrseq_vec_Init()                                      //
//                                                        //
// Description: Variable Initialization                   //
//                                                        //
// Input:     None                                        //
//                                                        //
// Return:    None                                        //
//********************************************************//
void pwrseq_vec_Init(void)
{
    pwrcell_Init(&pwrseq_vec_var.vout[0]);
    pwrcell_Init(&pwrseq_vec_var.vout[1]);

    pwrseq_vec_var.time_isr.t_1us = 0;
    pwrseq_vec_var.time.t_1us     = 0;
}

void pwrseq_vec_timer_1us_ISR(void)
{
    pwrseq_vec_var.time_isr.t_1us = 1;
}

//********************************************************//
// GPIO Reference Table                                   //
//********************************************************//
typedef struct { GPIO_T* port; UINT32 pin; } pwrseq_gpio_ref_t;
static const pwrseq_gpio_ref_t vout_gpio[2] = { { VOUT_0_PORT, VOUT_0_BIT }, { VOUT_1_PORT, VOUT_1_BIT } };

void pwrseq_vec_mainLoop(void)
{
UINT32 IRQ = m_oemsys_getIrq();

    if (pwrseq_vec_var.time_isr.t_1us)
    {
        m_oemsys_IrqDis();
        pwrseq_vec_var.time_isr.t_1us = 0;
        m_oemsys_setIrq(IRQ);
        pwrseq_vec_var.time.t_1us = 1;
    }

    // Power cell handlers begin ////////////////////////////////////////////////////
    pwrseq_vec_var.vout[0].hi.condition    = (oemgpio_DI_Get(EN));
    pwrseq_vec_var.vout[0].lo.condition    = 0;
    pwrseq_vec_var.vout[0].force.condition = 0;

    pwrseq_vec_var.vout[1].hi.condition    = (oemgpio_DI_Get(EN));
    pwrseq_vec_var.vout[1].lo.condition    = 0;
    pwrseq_vec_var.vout[1].force.condition = (oemgpio_DI_Get(EN));

    for (UINT8 i = 0; i < 2; i++)
        pwrcell_handle(&pwrseq_vec_var.vout[i], pwrseq_vec_var.time.t_1us, pwrseq_vec_var.time.t_1us, vout_gpio[i].port, vout_gpio[i].pin);
    // Power cell handlers end //////////////////////////////////////////////////////

    pwrseq_vec_var.time.t_1us = 0;
}
#endif  //PWRSEQ_VEC_C
