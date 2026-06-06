import pstats
with open('stats_tottime.txt', 'w') as f:
    p = pstats.Stats('profile.prof', stream=f)
    p.sort_stats('tottime')
    p.print_stats()

