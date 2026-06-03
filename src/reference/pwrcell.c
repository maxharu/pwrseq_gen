//********************************************************//
//     pwrcell.c                                          //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef PWRCELL_C
#define PWRCELL_C

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Global Veriables Declare                               //
//********************************************************//
void pwrcell_Init(pwrcell_t* info)
{
    info->hi.condition    = 0;
    info->hi.permit       = 0;
    info->hi.cnt          = 0;
    info->lo.condition    = 0;
    info->lo.permit       = 0;
    info->lo.cnt          = 0;
    info->force.condition = 0;
}


void pwrcell_handle(pwrcell_t* info, const UINT8 t_hi, const UINT8 t_lo, GPIO_T* port, UINT32 pin)
{
    if (info->force.condition)
    {
        info->hi.permit    = 0;
        info->lo.permit    = 0;
        info->hi.cnt       = 0;
        info->lo.cnt       = 0;
        
        if (info->force.polar) oemgpio_DO_High(port, pin);
        else                   oemgpio_DO_Low (port, pin);
    }
    else
    {
        if (oemgpio_DI_Get(port, pin))  //Output is high
        {
            info->hi.permit = 0;
            info->hi.cnt    = 0;
            
            if (!info->hi.condition || !info->lo.condition) info->lo.permit = 1;    // Set permit for high
            
            if (info->lo.permit && info->lo.condition) 
            {
                if (t_lo && (info->lo.cnt < info->lo.cycle)) info->lo.cnt++;
            }
            else
            {
                info->lo.cnt = 0;
            }
            
            if (info->lo.permit && info->lo.condition && (info->lo.cnt >= info->lo.cycle)) 
            {
                oemgpio_DO_Low(port, pin);
            }
        }
        else                            //Output is low
        {
            info->lo.permit = 0;
            info->lo.cnt    = 0;
            
            if (!info->hi.condition || !info->lo.condition) info->hi.permit = 1;    // Set permit for low
            
            if (info->hi.permit && info->hi.condition) 
            {
                if (t_hi && (info->hi.cnt < info->hi.cycle)) info->hi.cnt++;
            }
            else
            {
                info->hi.cnt = 0;
            }
            
            if (info->hi.permit && info->hi.condition && (info->hi.cnt >= info->hi.cycle)) 
            {
                oemgpio_DO_High(port, pin);
            }
        }
    }
}
#endif  //PWRCELL_C
