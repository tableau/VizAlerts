


class test_alert:
    def __init__(self, item_count=0):
        some_list = []

        if item_count > 0:
            some_list = range(0, item_count)

    def has_items(self):
        len(self.some_list)


test1 = test_alert(2)
#test2 = test_alert()

print test1.has_items()
#print test2.has_items()
