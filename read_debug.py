lines = open('football/debug/midnite_players_debug_belgium-v-egypt.txt', encoding='utf-8').readlines()
for i in range(516, 596):
    print(i+1, repr(lines[i].rstrip()))