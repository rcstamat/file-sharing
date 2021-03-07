# file-sharing
Two way (server-client) file sharing application meant to minimize network data flow.

The algorithm is a version of Andrew Tridgell's phd paper on which rsync is based.
When a file present on both hosts gets modified, only the delta between these 2 files gets transmitted.
The process involves breaking the file into chunks, calculating 2 hashes for each one,and then using a rolling hash method to identify the chunks that are common.
A detailed explanation can be found in his [paper](https://www.samba.org/~tridge/phd_thesis.pdf)

Use the following to find out how to get started:
> python3 server.py --help

> python3 client.py --help

A note on the file changing event mechanism.
Both PyInotify(formerly used) and watchdog (actual use) libraries give raw input as to what happens on the filesystem which can be confusing.
For watchdog there are 4 types of events generated:

* EVENT_TYPE_MOVED = 'moved'
* EVENT_TYPE_DELETED = 'deleted'
* EVENT_TYPE_CREATED = 'created'
* EVENT_TYPE_MODIFIED = 'modified'

But that doesn't necessary mean that when a file gets modified, a modified event gets triggered. A possible scenario is that a buffer will be created, then modified, and lastly renamed to the modified file's name.
Also bigger files will generate many modified events instead of one. Another example is deleting a file/folder using an IDE will not trigger a delete event, but a move event to the trash folder.
For this reason the events are filtered into the right boxes based on source, destination and files already present in the shared folder.

As big files will take a long time to be copied around, there is a need for handling their incomplete state until they are fully shareable. An approach was chosen to delay the transfer until no events get triggered for a couple seconds. This should be improved.

Files that are on both hosts but with different content are treated based on the mode parameter passed through the server. An example:

A, B, C, X and X* are files shared, X* is also X but with different content. If server contains A,B,X and client contains A,C,X* these are the 4 outcomes of the sync based on the mode selected:



|        	| Server 	| Client 	|
|:------:	|:------:	|:------:	|
|  Before sync	|    ABX	|    ACX*	|
|  Sync Mode 0 	|    ABCX* 	|    ABCX* 	|
|  Sync Mode 1 	|    ABCX 	|    ABCX 	|
|  Sync Mode 2 	|    ACX*  	|    ACX* 	|
|  Sync Mode 3 	|    ABX  	|    ABX  	|


- Mode 0: client only writes exclusive content to server
- Mode 1: server only writes exclusive content to client
- Mode 2: client overwrites server
- Mode 3: server overwrites client


Dependencies:

`pip install numpy`

`pip install watchdog`



