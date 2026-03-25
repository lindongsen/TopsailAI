'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''


# ai agent object
g_ai_agent = None

def set_ai_agent(agent):
    """ set agent object to global variable """
    if agent:
        global g_ai_agent
        g_ai_agent = agent
    return

def get_ai_agent():
    """ return a agent object """
    return g_ai_agent
