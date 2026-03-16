from datetime import timedelta


class NFDumpCommandBuilder:

    @staticmethod
    def generate_time_range(target_datetime, minute_margin):

        start = target_datetime - timedelta(minutes=minute_margin)
        end = target_datetime + timedelta(minutes=minute_margin)

        return start, end

    @classmethod
    def build(cls, ip, target_datetime, minute_margin):

        start, end = cls.generate_time_range(target_datetime, minute_margin)

        folder = target_datetime.strftime("%Y/%m/%d")

        time_range = (
            f"{start.strftime('%Y/%m/%d.%H:%M:%S')}-"
            f"{end.strftime('%Y/%m/%d.%H:%M:%S')}"
        )

        filter_rule = f"xip {ip}"

        command = f"nfdump -R {folder} -t {time_range} '{filter_rule}' -o json"

        return command
