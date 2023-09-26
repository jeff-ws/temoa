"""
Quick utility script to analyze the distribution of capacities within a scenario database
"""
import itertools
import os.path
import sqlite3

from matplotlib import pyplot as plt



# Written by:  J. F. Hyink
# jeff@westernspark.us
# https://westernspark.us

# Created on:  7/18/23

source_db_file = os.path.join('..', '..', 'data_files', 'US_9R_TS.sqlite')
print(source_db_file)
res =[]
try:
    con = sqlite3.connect(source_db_file)
    cur = con.cursor()
    cur.execute('SELECT maxcap FROM MaxCapacity')
    for row in cur:
        res.append(row)

except sqlite3.Error as e:
    print(e)

finally:
    con.close()
# sample first 10 for QA
# for row in res[:10]:
#     print(row)

# chain them together into a list
caps = list(itertools.chain(*res))

cutoff = 1 # GW : An arbitrary cutoff between big and small capacity systems.
small_cap_sources = [c for c in caps if c <= cutoff]
large_cap_sources = [c for c in caps if c > cutoff]

aggregate_small_cap = sum(small_cap_sources)
aggregate_large_cap = sum(large_cap_sources)

print(f'{len(small_cap_sources)} small cap sources account for: {aggregate_small_cap: 0.1f} GW')
print(f'{len(large_cap_sources)} large cap sources account for: {aggregate_large_cap: 0.1f} GW')

plt.hist(caps, bins=100)
plt.show()


# make a cumulative contribution plot
caps.sort()
total_cap = sum(caps)
cumulative_caps = [caps[0]/total_cap, ]
for i, cap in enumerate(caps[1:]):
    cumulative_caps.append(cap/total_cap + cumulative_caps[i])

plt.plot(range(len(cumulative_caps)), cumulative_caps)
plt.xlabel('Aggregated Sources')
plt.ylabel('Proportion of Total Capacity')
plt.title('Aggregate Capacity vs. Number of Sources')

plt.show()