//********************************************************//
//     pwrcell.h                                          //
//                                                        //
//     Supermicro Computer Confidential                   //
//                                                        //
//     Copyright (c) 2026 by Supermicro Computer          //
//     All rights reserved                                //
//                                                        //
//********************************************************//
#ifndef PWRCELL_H
#define PWRCELL_H

//********************************************************//
// Include File                                           //
//********************************************************//
#include "_user.h"

//********************************************************//
// Definitions                                            //
//********************************************************//
typedef struct
{
    UINT8 condition;
    UINT8 permit;
    UINT8 cnt;
    const UINT8 cycle;
}pwrcell_HL_t;

typedef struct
{
    UINT8 condition;
    const UINT8 polar;
}pwrcell_F_t;

typedef struct
{
    pwrcell_HL_t hi;
    pwrcell_HL_t lo;
    pwrcell_F_t force;
}pwrcell_t;

//********************************************************//
// Function Declaration                                   //
//********************************************************//
void pwrcell_Init(pwrcell_t* info);
void pwrcell_handle(pwrcell_t* info, const UINT8 t_force, const UINT8 t_hi, const UINT8 t_lo, GPIO_T* port, UINT32 pin);

#endif  //PWRCELL_H
